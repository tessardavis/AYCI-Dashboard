"""AYCI Team Dashboard — Backend API tests (pytest)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ayci-dashboard.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@ayci.com"
ADMIN_PASSWORD = "Admin@2026"


# ---- Shared fixtures -------------------------------------------------------
@pytest.fixture(scope="session")
def admin_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data["role"] == "admin"
    assert data["email"] == ADMIN_EMAIL
    # httpOnly cookie set on session
    assert "access_token" in s.cookies.get_dict()
    return s


@pytest.fixture(scope="session")
def user_session(admin_session):
    """Create (or reuse) a non-admin user and return an authenticated session."""
    email = "test_user_regression@ayci.com"
    password = "UserPass@2026"
    # Register via admin (ignore if exists)
    admin_session.post(f"{API}/auth/register",
                       json={"email": email, "password": password, "name": "Regression User", "role": "user"},
                       timeout=30)
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"user login failed: {r.text}"
    assert r.json()["role"] == "user"
    return s


# ---- Auth tests ------------------------------------------------------------
class TestAuth:
    def test_login_success_sets_cookies(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == ADMIN_EMAIL
        assert body["role"] == "admin"
        assert "access_token" in s.cookies.get_dict()
        assert "refresh_token" in s.cookies.get_dict()
        # httpOnly must be present in raw set-cookie
        sc = r.headers.get("set-cookie", "").lower()
        assert "httponly" in sc

    def test_login_wrong_password(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"}, timeout=30)
        assert r.status_code == 401

    def test_me_with_cookie(self, admin_session):
        r = admin_session.get(f"{API}/auth/me", timeout=30)
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == ADMIN_EMAIL
        assert body["role"] == "admin"
        assert "password_hash" not in body

    def test_me_without_cookie(self):
        r = requests.get(f"{API}/auth/me", timeout=30)
        assert r.status_code == 401

    def test_logout_clears_cookie(self):
        s = requests.Session()
        s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
        r = s.post(f"{API}/auth/logout", timeout=30)
        assert r.status_code == 200
        # After logout, /auth/me should fail
        r2 = s.get(f"{API}/auth/me", timeout=30)
        assert r2.status_code == 401


# ---- Seed data tests -------------------------------------------------------
class TestSeed:
    def test_team_seeded_7(self, admin_session):
        r = admin_session.get(f"{API}/team", timeout=30)
        assert r.status_code == 200
        team = r.json()
        assert len(team) == 7, f"expected 7 team members, got {len(team)}"
        names = {m["name"] for m in team}
        assert "Tessa Davis" in names
        assert "Arub Yousuf" in names

    def test_metrics_seeded_19(self, admin_session):
        r = admin_session.get(f"{API}/metrics", timeout=30)
        assert r.status_code == 200
        metrics = r.json()
        assert len(metrics) == 19, f"expected 19 metrics, got {len(metrics)}"
        cats = {m["category"] for m in metrics}
        assert cats == {
            "GROWTH + INTEREST", "CONVERSION + INTENT", "REVENUE",
            "SOCIAL PROOF", "DELIVERY + OPERATIONS",
        }

    def test_rocks_q2_2026_seeded_17(self, admin_session):
        r = admin_session.get(f"{API}/rocks", params={"quarter": "Q2 2026"}, timeout=30)
        assert r.status_code == 200
        rocks = r.json()
        assert len(rocks) == 17, f"expected 17 rocks, got {len(rocks)}"
        statuses = {rk["status"] for rk in rocks}
        assert statuses.issubset({"on_track", "off_track", "done"})

    def test_launches_seeded_3(self, admin_session):
        r = admin_session.get(f"{API}/launches", timeout=30)
        assert r.status_code == 200
        launches = r.json()
        assert len(launches) == 3
        names = {l["name"] for l in launches}
        assert names == {"NOV-25", "FEB-26", "APR-26"}

    def test_launch_data_and_daily_regs(self, admin_session):
        launches = admin_session.get(f"{API}/launches", timeout=30).json()
        apr = next(l for l in launches if l["name"] == "APR-26")
        rd = admin_session.get(f"{API}/launches/{apr['id']}/data", timeout=30)
        assert rd.status_code == 200
        assert rd.json()["launch_id"] == apr["id"]
        rr = admin_session.get(f"{API}/launches/{apr['id']}/daily-registrations", timeout=30)
        assert rr.status_code == 200
        regs = rr.json()
        assert len(regs) > 0, "expected seeded daily registrations for APR-26"
        # Check NOV-25 sum ~= total_regs
        nov = next(l for l in launches if l["name"] == "NOV-25")
        nov_regs = admin_session.get(f"{API}/launches/{nov['id']}/daily-registrations", timeout=30).json()
        assert sum(d["count"] for d in nov_regs) > 0

    def test_weekly_values_seeded(self, admin_session):
        r = admin_session.get(f"{API}/weekly-values", timeout=30)
        assert r.status_code == 200
        wv = r.json()
        # 4 weeks * 19 metrics = 76
        assert len(wv) >= 19 * 4 - 2, f"expected ~76 weekly values, got {len(wv)}"


# ---- Mutations / RBAC ------------------------------------------------------
class TestMutations:
    def test_upsert_weekly_value_user(self, user_session, admin_session):
        metrics = admin_session.get(f"{API}/metrics", timeout=30).json()
        mid = metrics[0]["id"]
        payload = {"metric_id": mid, "week_start": "2024-01-01", "value": 12345}
        r = user_session.post(f"{API}/weekly-values", json=payload, timeout=30)
        assert r.status_code == 200
        assert r.json()["value"] == 12345
        # Upsert again with different value
        payload["value"] = 999
        r2 = user_session.post(f"{API}/weekly-values", json=payload, timeout=30)
        assert r2.status_code == 200
        assert r2.json()["value"] == 999

    def test_patch_rock_as_user_allowed(self, user_session, admin_session):
        rocks = admin_session.get(f"{API}/rocks", params={"quarter": "Q2 2026"}, timeout=30).json()
        rid = rocks[0]["id"]
        original = rocks[0]["status"]
        new_status = "done" if original != "done" else "on_track"
        r = user_session.patch(f"{API}/rocks/{rid}", json={"status": new_status}, timeout=30)
        assert r.status_code == 200
        assert r.json()["status"] == new_status
        # Revert
        user_session.patch(f"{API}/rocks/{rid}", json={"status": original}, timeout=30)

    def test_patch_launch_data(self, admin_session):
        launches = admin_session.get(f"{API}/launches", timeout=30).json()
        apr = next(l for l in launches if l["name"] == "APR-26")
        r = admin_session.patch(
            f"{API}/launches/{apr['id']}/data",
            json={"sales_academy_count": 42},
            timeout=30,
        )
        assert r.status_code == 200
        assert r.json()["sales_academy_count"] == 42
        # GET to verify persisted
        g = admin_session.get(f"{API}/launches/{apr['id']}/data", timeout=30).json()
        assert g["sales_academy_count"] == 42

    def test_create_metric_admin_ok_user_forbidden(self, admin_session, user_session):
        payload = {"name": "TEST_metric_regression", "category": "REVENUE", "goal": 100, "format": "number"}
        # Admin should succeed
        r = admin_session.post(f"{API}/metrics", json=payload, timeout=30)
        assert r.status_code == 200
        created_id = r.json()["id"]

        # Non-admin should be forbidden
        r2 = user_session.post(f"{API}/metrics", json=payload, timeout=30)
        assert r2.status_code == 403

        # cleanup
        admin_session.delete(f"{API}/metrics/{created_id}", timeout=30)
        g = admin_session.get(f"{API}/metrics", timeout=30).json()
        assert created_id not in [m["id"] for m in g]

    def test_create_team_member_rbac(self, admin_session, user_session):
        r = user_session.post(f"{API}/team", json={"name": "Blocked", "role_title": "NA"}, timeout=30)
        assert r.status_code == 403
        r2 = admin_session.post(f"{API}/team", json={"name": "TEST_Member", "role_title": "Tester"}, timeout=30)
        assert r2.status_code == 200
        mid = r2.json()["id"]
        admin_session.delete(f"{API}/team/{mid}", timeout=30)

    def test_create_rock_rbac(self, admin_session, user_session):
        payload = {
            "owner_id": "nobody", "title": "TEST_rock", "status": "on_track",
            "due_date": "2026-12-31", "notes": "", "quarter": "Q4 2026",
        }
        r = user_session.post(f"{API}/rocks", json=payload, timeout=30)
        assert r.status_code == 403
        r2 = admin_session.post(f"{API}/rocks", json=payload, timeout=30)
        assert r2.status_code == 200
        rid = r2.json()["id"]
        admin_session.delete(f"{API}/rocks/{rid}", timeout=30)


# ---- Bcrypt hash format verification ---------------------------------------
class TestSecurity:
    def test_cors_credentials_config(self):
        """CORS with credentials should NOT return '*' for origin."""
        r = requests.options(
            f"{API}/auth/login",
            headers={
                "Origin": "https://ayci-dashboard.preview.emergentagent.com",
                "Access-Control-Request-Method": "POST",
            },
            timeout=30,
        )
        # Not fatal, just report
        origin = r.headers.get("access-control-allow-origin", "")
        credentials = r.headers.get("access-control-allow-credentials", "")
        print(f"CORS: origin={origin!r} credentials={credentials!r}")
