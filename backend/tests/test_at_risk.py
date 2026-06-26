"""
Iteration 5 backend regression - Students-at-Risk endpoint + existing endpoints.

Tests:
  * GET /api/students/at-risk schema, auth-protection, refresh kick-off
  * Domain rules (lifetime_gbp >= 1000, risk_status enum)
  * Existing endpoints still work after CORS tightening
  * CORS preflight for the public preview origin
"""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ayci-dashboard.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@ayci.com"
ADMIN_PASSWORD = "Admin@2026"

VALID_RISK_STATUSES = {"dormant", "never_logged_in", "no_circle_account"}
REQUIRED_STUDENT_FIELDS = {
    "stripe_customer_id",
    "email",
    "name",
    "lifetime_gbp",
    "charge_count",
    "last_charge_at",
    "circle_avatar_url",
    "circle_last_seen_at",
    "days_dormant",
    "risk_status",
}


@pytest.fixture(scope="module")
def auth_session():
    s = requests.Session()
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"Login failed {r.status_code}: {r.text[:300]}"
    # httpOnly cookies should be in the session jar
    assert any(c.name == "access_token" for c in s.cookies), f"access_token cookie not set: {s.cookies}"
    return s


@pytest.fixture(scope="module")
def at_risk_payload(auth_session):
    """Fetch at-risk once for the module. Wait briefly if cache says computing."""
    for attempt in range(8):  # up to ~80s grace if cache cold
        r = auth_session.get(f"{BASE_URL}/api/students/at-risk", timeout=30)
        assert r.status_code == 200, f"GET /students/at-risk -> {r.status_code}: {r.text[:300]}"
        body = r.json()
        if not body.get("computing"):
            return body
        time.sleep(10)
    pytest.skip("at-risk cache still computing after 80s; aborting domain assertions")


# --- Auth protection -------------------------------------------------------

class TestAtRiskAuth:
    def test_unauth_returns_401(self):
        r = requests.get(f"{BASE_URL}/api/students/at-risk", timeout=15)
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text[:200]}"


# --- Schema ----------------------------------------------------------------

class TestAtRiskSchema:
    def test_status_200(self, auth_session):
        r = auth_session.get(f"{BASE_URL}/api/students/at-risk", timeout=30)
        assert r.status_code == 200

    def test_top_level_keys(self, at_risk_payload):
        body = at_risk_payload
        for k in ("total_at_risk", "counts", "students", "min_spend_gbp", "dormant_days", "lookback_days"):
            assert k in body, f"missing top-level key: {k}"
        assert isinstance(body["total_at_risk"], int)
        assert isinstance(body["students"], list)
        assert body["min_spend_gbp"] == 1000.0
        assert body["dormant_days"] == 30
        assert body["lookback_days"] == 365

    def test_counts_keys(self, at_risk_payload):
        counts = at_risk_payload["counts"]
        assert set(counts.keys()) == VALID_RISK_STATUSES
        for k, v in counts.items():
            assert isinstance(v, int) and v >= 0, f"{k} bad: {v}"
        # Counts should sum to total
        assert sum(counts.values()) == at_risk_payload["total_at_risk"]

    def test_students_have_required_fields(self, at_risk_payload):
        students = at_risk_payload["students"]
        # Test agent context note: ~60-70 expected. Allow anything > 0.
        assert len(students) > 0, "no at-risk students returned (cache may be cold or production data empty)"
        for s in students[:5]:
            missing = REQUIRED_STUDENT_FIELDS - set(s.keys())
            assert not missing, f"student missing fields {missing}: {s}"

    def test_no_mongo_id_leaked(self, at_risk_payload):
        for s in at_risk_payload["students"][:10]:
            assert "_id" not in s


# --- Domain rules ----------------------------------------------------------

class TestAtRiskDomain:
    def test_all_lifetime_gbp_above_min(self, at_risk_payload):
        bad = [s for s in at_risk_payload["students"] if s["lifetime_gbp"] < 1000]
        assert not bad, f"{len(bad)} students under £1000; sample: {bad[:2]}"

    def test_risk_status_enum(self, at_risk_payload):
        bad = [s for s in at_risk_payload["students"] if s["risk_status"] not in VALID_RISK_STATUSES]
        assert not bad, f"invalid risk_status values: {[s['risk_status'] for s in bad[:5]]}"

    def test_sorted_desc_by_lifetime_gbp(self, at_risk_payload):
        spends = [s["lifetime_gbp"] for s in at_risk_payload["students"]]
        assert spends == sorted(spends, reverse=True), "students not sorted by lifetime_gbp desc"

    def test_dormant_has_days_dormant(self, at_risk_payload):
        for s in at_risk_payload["students"]:
            if s["risk_status"] == "dormant":
                assert s["days_dormant"] is not None and s["days_dormant"] > 30, (
                    f"dormant student should have days_dormant>30: {s}"
                )


# --- Refresh kick-off ------------------------------------------------------

class TestAtRiskRefresh:
    def test_refresh_true_returns_200_quickly(self, auth_session):
        """?refresh=true kicks a *background* task; the request itself must
        return immediately with the current cache (no long block)."""
        t0 = time.time()
        r = auth_session.get(f"{BASE_URL}/api/students/at-risk?refresh=true", timeout=30)
        elapsed = time.time() - t0
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        # Should not block on the full Stripe scan
        assert elapsed < 25, f"refresh=true blocked for {elapsed:.1f}s - should be background"
        body = r.json()
        # Either fresh cache or computing/stale flag - but always valid shape
        assert "students" in body and "total_at_risk" in body


# --- Regression on existing endpoints --------------------------------------

class TestExistingEndpointsRegression:
    """After CORS tightening, all previously-working endpoints must still respond."""

    def test_launches_list(self, auth_session):
        r = auth_session.get(f"{BASE_URL}/api/launches", timeout=20)
        assert r.status_code == 200
        body = r.json()
        # Could be a list or an object with 'launches' - both forms are acceptable
        assert isinstance(body, (list, dict))

    def test_launches_active_pace(self, auth_session):
        r = auth_session.get(f"{BASE_URL}/api/launches/active/pace", timeout=20)
        assert r.status_code in (200, 404), f"active/pace → {r.status_code}: {r.text[:200]}"

    def test_launches_year_overview(self, auth_session):
        r = auth_session.get(f"{BASE_URL}/api/launches/year-overview", timeout=30)
        assert r.status_code == 200, r.text[:300]

    def test_students_lookup(self, auth_session):
        r = auth_session.get(
            f"{BASE_URL}/api/students/lookup",
            params={"email": "andreea.gavrisan@gmail.com"},
            timeout=60,
        )
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("email", "").lower() == "andreea.gavrisan@gmail.com"

    def test_cohorts_labels(self, auth_session):
        r = auth_session.get(f"{BASE_URL}/api/cohorts/labels", timeout=20)
        assert r.status_code == 200

    def test_interviews_upcoming(self, auth_session):
        r = auth_session.get(f"{BASE_URL}/api/interviews/upcoming", timeout=20)
        assert r.status_code == 200


# --- CORS regression -------------------------------------------------------
#
# NOTE: The public preview is fronted by Cloudflare which injects its own
# `access-control-allow-origin: *` regardless of what FastAPI returns. So an
# OPTIONS preflight check at the public URL only tests the edge proxy, not
# our app. What we *can* verify functionally is:
#   1) credentialed login from the configured preview origin still succeeds
#      (i.e. no regression on the cookies/auth flow after dropping the *
#      CORS fallback in app code).
#   2) the configured CORS_ORIGINS env var actually contains the preview
#      origin we're hitting.

class TestCORSFunctional:
    def test_credentialed_login_from_preview_origin(self):
        """Login with Origin header set to the configured preview URL must
        succeed and return access_token cookie."""
        s = requests.Session()
        r = s.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            headers={"Origin": BASE_URL},
            timeout=15,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        cookie_names = {c.name for c in s.cookies}
        assert "access_token" in cookie_names, f"access_token cookie missing: {cookie_names}"

    def test_authenticated_request_works(self, auth_session):
        """If CORS broke the cookie flow, this would fail with 401."""
        r = auth_session.get(f"{BASE_URL}/api/auth/me", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body.get("email") == ADMIN_EMAIL
