"""AYCI iteration 6 - change-password, past_coaches, HeroBanner regression, RBAC.

Covers:
- POST /api/auth/change-password (4 cases) + auth required
- GET /api/interviews/upcoming past_coaches enrichment + warm-cache SLA
- Sidebar/board permission regressions for the 5 provisioned team users
- Coach 403 regression
"""
import os
import time
import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://ayci-dashboard.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@ayci.com"
ADMIN_PASSWORD = "Admin@2026"
COACH_EMAIL = "coach@ayci.com"
COACH_PASSWORD = "Coach@2026"

TEAM_FULL = ["arub@medicalinterviewprep.com", "oksana@medicalinterviewprep.com"]
TEAM_NO_LAUNCHES = [
    "coralie@medicalinterviewprep.com",
    "becky@medicalinterviewprep.com",
    "anoop.chidam@gmail.com",
]
TEAM_PASSWORD = "Welcome@AYCI2026"


# ---- fixtures --------------------------------------------------------------
@pytest.fixture(scope="session")
def admin_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"admin login: {r.status_code} {r.text}"
    return s


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    return s, r


def _get_user_id(admin_session, email):
    r = admin_session.get(f"{API}/admin/users", timeout=30)
    assert r.status_code == 200
    users = r.json().get("users", [])
    for u in users:
        if u["email"].lower() == email.lower():
            return u["id"]
    return None


# ---- Change password -------------------------------------------------------
class TestChangePassword:
    def test_requires_auth(self):
        r = requests.post(f"{API}/auth/change-password",
                          json={"current_password": "x", "new_password": "yyyyyyyy"},
                          timeout=30)
        assert r.status_code == 401

    def test_full_flow_for_becky(self, admin_session):
        """Run all 4 cases against becky, then reset back to Welcome@AYCI2026."""
        email = "becky@medicalinterviewprep.com"
        orig_pw = TEAM_PASSWORD
        new_pw = "Brand-New-Pass-2026!"

        # login becky
        s, r = _login(email, orig_pw)
        assert r.status_code == 200, f"becky login failed: {r.text}"

        # (b) new < 8 chars
        r = s.post(f"{API}/auth/change-password",
                   json={"current_password": orig_pw, "new_password": "short"},
                   timeout=30)
        assert r.status_code == 400
        assert "at least 8" in (r.json().get("detail") or "").lower()

        # (c) new == current
        r = s.post(f"{API}/auth/change-password",
                   json={"current_password": orig_pw, "new_password": orig_pw},
                   timeout=30)
        assert r.status_code == 400
        assert "differ" in (r.json().get("detail") or "").lower()

        # (a) wrong current (new valid, differs from current)
        r = s.post(f"{API}/auth/change-password",
                   json={"current_password": "WrongPass123!", "new_password": new_pw},
                   timeout=30)
        assert r.status_code == 400
        assert "current password is incorrect" in (r.json().get("detail") or "").lower()

        # (d) valid → 200
        r = s.post(f"{API}/auth/change-password",
                   json={"current_password": orig_pw, "new_password": new_pw},
                   timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # Verify old password no longer works
        _, r_old = _login(email, orig_pw)
        assert r_old.status_code == 401, "old password should be rejected"

        # Verify new password works
        _, r_new = _login(email, new_pw)
        assert r_new.status_code == 200, "new password should log in"

        # RESET: admin patches password back
        uid = _get_user_id(admin_session, email)
        assert uid, "could not find becky in admin/users"
        r = admin_session.patch(f"{API}/admin/users/{uid}",
                                json={"password": orig_pw},
                                timeout=30)
        assert r.status_code == 200, f"password reset failed: {r.text}"

        # Verify reset worked
        _, r_reset = _login(email, orig_pw)
        assert r_reset.status_code == 200, "reset password should log in"


# ---- Upcoming interviews + past_coaches ------------------------------------
class TestUpcomingInterviews:
    def test_past_coaches_and_sla(self, admin_session):
        t0 = time.time()
        r = admin_session.get(
            f"{API}/interviews/upcoming",
            params={"academy_days": 7, "private_days": 14},
            timeout=60,
        )
        elapsed = time.time() - t0
        assert r.status_code == 200, r.text
        body = r.json()
        assert "academy" in body and "private" in body
        assert isinstance(body["academy"], list)
        assert isinstance(body["private"], list)

        # warm-cache SLA (review says <5s; cold call can be slower on first hit)
        # Make a second call to guarantee warm cache.
        t0 = time.time()
        r2 = admin_session.get(
            f"{API}/interviews/upcoming",
            params={"academy_days": 7, "private_days": 14},
            timeout=30,
        )
        warm_elapsed = time.time() - t0
        assert r2.status_code == 200
        assert warm_elapsed < 5, f"warm cache response took {warm_elapsed:.2f}s (expected <5s)"
        print(f"interviews/upcoming: cold={elapsed:.2f}s warm={warm_elapsed:.2f}s")

        body = r2.json()
        # Collect all students from both lists
        students = []
        for row in body["academy"]:
            students.extend(row.get("students", []))
        students.extend(body["private"])

        # At least one student should have past_coaches populated
        enriched = [s for s in students if s.get("past_coaches")]
        print(f"students with past_coaches: {len(enriched)}/{len(students)}")
        assert len(enriched) >= 1, "expected at least one student with past_coaches"

        # Validate structure of one entry
        sample = enriched[0]["past_coaches"]
        assert isinstance(sample, list)
        assert 1 <= len(sample) <= 3, "past_coaches should be top-3"
        for coach in sample:
            assert "name" in coach
            assert "count" in coach
            assert "last_at" in coach
            assert isinstance(coach["count"], int)
            assert coach["count"] >= 1

        # For students without past_coaches field must be null or empty list (not missing-and-undefined)
        for s in students:
            pc = s.get("past_coaches", None)
            assert pc is None or isinstance(pc, list)


# ---- Permission regressions ------------------------------------------------
class TestPermissions:
    def test_coach_403(self):
        s, r = _login(COACH_EMAIL, COACH_PASSWORD)
        assert r.status_code == 200, f"coach login: {r.text}"
        r1 = s.get(f"{API}/students/at-risk", timeout=30)
        assert r1.status_code == 403, f"coach /students/at-risk: {r1.status_code}"
        r2 = s.get(f"{API}/cohorts/labels", timeout=30)
        assert r2.status_code == 403, f"coach /cohorts/labels: {r2.status_code}"

    @pytest.mark.parametrize("email", TEAM_FULL)
    def test_full_team_users_login_and_boards(self, email):
        s, r = _login(email, TEAM_PASSWORD)
        assert r.status_code == 200, f"{email} login: {r.text}"
        me = s.get(f"{API}/auth/me", timeout=30).json()
        boards = set(me.get("board_access", []))
        expected = {"weekly_scorecard", "quarterly_rocks", "launches", "cohort",
                    "interviews", "students", "at_risk"}
        assert expected.issubset(boards), f"{email} boards={boards}"

    @pytest.mark.parametrize("email", TEAM_NO_LAUNCHES)
    def test_no_launches_team_users(self, email):
        s, r = _login(email, TEAM_PASSWORD)
        assert r.status_code == 200, f"{email} login: {r.text}"
        me = s.get(f"{API}/auth/me", timeout=30).json()
        boards = set(me.get("board_access", []))
        assert "launches" not in boards, f"{email} should NOT have launches: {boards}"
        # Should have the other 6
        expected = {"weekly_scorecard", "quarterly_rocks", "cohort",
                    "interviews", "students", "at_risk"}
        assert expected.issubset(boards), f"{email} missing boards: {expected - boards}"


# ---- Launch dashboard regression (hero refactor) ---------------------------
class TestLaunchRegression:
    def test_launches_still_list(self, admin_session):
        r = admin_session.get(f"{API}/launches", timeout=30)
        assert r.status_code == 200
        launches = r.json()
        assert len(launches) >= 3
        names = {lc["name"] for lc in launches}
        # The names are full month format; just assert the APR-26 cohort exists under either naming.
        assert any("April" in n or "APR" in n for n in names), f"missing April launch in {names}"

    def test_launch_data_still_returns(self, admin_session):
        launches = admin_session.get(f"{API}/launches", timeout=30).json()
        apr = next((lc for lc in launches if "April" in lc["name"] or "APR" in lc["name"]), launches[0])
        rd = admin_session.get(f"{API}/launches/{apr['id']}/data", timeout=30)
        assert rd.status_code == 200
        body = rd.json()
        assert body["launch_id"] == apr["id"]

    def test_active_pace_and_year_overview(self, admin_session):
        r1 = admin_session.get(f"{API}/launches/active/pace", timeout=30)
        assert r1.status_code == 200
        r2 = admin_session.get(f"{API}/launches/year-overview", timeout=30)
        assert r2.status_code == 200
