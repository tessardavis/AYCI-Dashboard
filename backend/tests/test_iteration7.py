"""
Iteration 7 - Private Tier Utilisation + Student Lookup name-fallback fix.

Tests:
  1) GET /api/interviews/private-tier-utilisation?days=14 shape + auth + caching
  2) days param validation (7/14/30 ok, 5/60 -> 400)
  3) Board access enforcement (no-cookie -> 401; verify admin has 'interviews')
  4) Stale-while-revalidate caching (2nd call within 30 min is fast)
  5) Bug fix: deepika.t.reddy@gmail.com now returns monday.found=true
     with name fallback; without name param -> found=false
  6) Normal student lookup still works (andreea.gavrisan@gmail.com)
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_EMAIL = "admin@ayci.com"
ADMIN_PW = "Admin@2026"


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PW},
               timeout=20)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def anon_session():
    return requests.Session()


# ---------- auth / board access -------------------------------------------
def test_auth_me_admin_has_interviews_board(admin_session):
    r = admin_session.get(f"{BASE_URL}/api/auth/me", timeout=10)
    assert r.status_code == 200
    me = r.json()
    assert me["email"] == ADMIN_EMAIL
    assert "interviews" in me["board_access"]


def test_utilisation_requires_auth(anon_session):
    r = anon_session.get(
        f"{BASE_URL}/api/interviews/private-tier-utilisation?days=14",
        timeout=20,
    )
    # Must block - 401 (no creds) or 403 (no board)
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


# ---------- days validation ------------------------------------------------
@pytest.mark.parametrize("bad_days", [5, 60, 1, 0, -1, 100])
def test_utilisation_invalid_days_returns_400(admin_session, bad_days):
    r = admin_session.get(
        f"{BASE_URL}/api/interviews/private-tier-utilisation",
        params={"days": bad_days},
        timeout=30,
    )
    assert r.status_code == 400, f"days={bad_days} expected 400, got {r.status_code}"


@pytest.mark.parametrize("good_days", [7, 14, 30])
def test_utilisation_valid_days_returns_200(admin_session, good_days):
    r = admin_session.get(
        f"{BASE_URL}/api/interviews/private-tier-utilisation",
        params={"days": good_days},
        timeout=90,
    )
    assert r.status_code == 200, f"days={good_days} expected 200, got {r.status_code}"
    body = r.json()
    assert body["window_days"] == good_days


# ---------- shape / logic --------------------------------------------------
def test_utilisation_14d_shape(admin_session):
    r = admin_session.get(
        f"{BASE_URL}/api/interviews/private-tier-utilisation?days=14",
        timeout=90,
    )
    assert r.status_code == 200
    body = r.json()
    # top-level
    assert body["window_days"] == 14
    assert "summary_by_tier" in body
    assert "Private Plus" in body["summary_by_tier"]
    assert "VIP" in body["summary_by_tier"]
    for tier_sum in body["summary_by_tier"].values():
        for k in ("total", "on_track", "flagged"):
            assert k in tier_sum
            assert isinstance(tier_sum[k], int)
    assert isinstance(body["flagged"], list)
    assert isinstance(body["on_track"], list)
    assert "last_refreshed" in body

    required_row_keys = {
        "name", "monday_id", "monday_url", "tier", "tier_raw",
        "interview_date", "days_until", "videos_submitted",
        "videos_allowance", "videos_min", "videos_pct",
        "calls_used", "calls_allowance", "calls_min", "calls_pct",
        "logic", "reasons",
    }
    for row in body["flagged"] + body["on_track"]:
        missing = required_row_keys - row.keys()
        assert not missing, f"row missing keys {missing}: {row}"
        assert row["tier"] in ("Private Plus", "VIP")
        assert isinstance(row["reasons"], list)

    # on_track rows must have empty reasons
    for row in body["on_track"]:
        assert row["reasons"] == [], f"on_track row should have empty reasons: {row}"

    # flagged rows should have at least one reason
    for row in body["flagged"]:
        assert len(row["reasons"]) >= 1, f"flagged row missing reasons: {row}"


def test_utilisation_caching_is_fast_second_call(admin_session):
    # Force refresh first
    r1 = admin_session.get(
        f"{BASE_URL}/api/interviews/private-tier-utilisation",
        params={"days": 14, "refresh": "true"},
        timeout=120,
    )
    assert r1.status_code == 200
    # Second call should hit cache and be sub-3s (SWR cache claim: sub-300ms,
    # but we allow network overhead on preview)
    t0 = time.time()
    r2 = admin_session.get(
        f"{BASE_URL}/api/interviews/private-tier-utilisation?days=14",
        timeout=120,
    )
    elapsed = time.time() - t0
    assert r2.status_code == 200
    assert elapsed < 3.0, f"warm call took {elapsed:.2f}s - cache not working"


# ---------- student lookup name-fallback bug fix ---------------------------
def test_deepika_lookup_without_name_not_found_on_monday(admin_session):
    # Baseline: email-only lookup should NOT find Deepika on Monday
    r = admin_session.get(
        f"{BASE_URL}/api/students/lookup",
        params={"email": "deepika.t.reddy@gmail.com"},
        timeout=60,
    )
    assert r.status_code == 200
    body = r.json()
    monday = body.get("monday") or {}
    # The fix: WITHOUT name param, monday should be found=false
    assert monday.get("found") is False, (
        f"expected monday.found=false without name, got {monday}"
    )


def test_deepika_lookup_with_name_falls_back_to_monday(admin_session):
    # With name param, Monday fallback finds her and reports tier
    r = admin_session.get(
        f"{BASE_URL}/api/students/lookup",
        params={"email": "deepika.t.reddy@gmail.com", "name": "Deepika Reddy"},
        timeout=60,
    )
    assert r.status_code == 200
    body = r.json()
    monday = body.get("monday") or {}
    assert monday.get("found") is True, (
        f"expected monday.found=true with name fallback, got {monday}"
    )
    data = monday.get("data") or {}
    # Tier lives at data.columns.Tier.text (Monday column structure)
    cols = data.get("columns") or {}
    tier_col = cols.get("Tier") or {}
    tier = tier_col.get("text") or data.get("tier") or data.get("Tier") or ""
    # Per review: should be 'Upgrade Private Plus'
    assert "Upgrade Private Plus" in str(tier), (
        f"expected tier to include 'Upgrade Private Plus', got {tier!r}"
    )
    # Display Name / Name should match
    assert "Deepika" in (data.get("name") or "")


def test_normal_student_lookup_still_works(admin_session):
    r = admin_session.get(
        f"{BASE_URL}/api/students/lookup",
        params={"email": "andreea.gavrisan@gmail.com"},
        timeout=60,
    )
    assert r.status_code == 200
    body = r.json()
    # At least one of these platforms should find them
    monday = body.get("monday") or {}
    circle = body.get("circle") or {}
    found_anywhere = monday.get("found") or circle.get("found")
    assert found_anywhere, f"andreea not found anywhere: monday={monday.get('found')} circle={circle.get('found')}"
