"""AYCI — Student Lookup and related regression tests (pytest)."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@ayci.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@2026")

REAL_EMAIL = "andreea.gavrisan@gmail.com"
FAKE_EMAIL = "nobody-random-test@example.com"


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return s


# ---- Student lookup tests --------------------------------------------------
class TestStudentLookup:
    def test_lookup_missing_email_returns_400(self, admin_session):
        r = admin_session.get(f"{API}/students/lookup", timeout=30)
        assert r.status_code in (400, 422), f"expected 400/422, got {r.status_code}"

    def test_lookup_invalid_email_returns_400(self, admin_session):
        r = admin_session.get(f"{API}/students/lookup", params={"email": "not-an-email"}, timeout=30)
        assert r.status_code in (400, 422), f"expected 400/422, got {r.status_code}: {r.text}"

    def test_lookup_unauth_returns_401(self):
        r = requests.get(f"{API}/students/lookup", params={"email": REAL_EMAIL}, timeout=30)
        assert r.status_code == 401, f"expected 401 unauth, got {r.status_code}"

    def test_lookup_fake_email_all_not_found_fast(self, admin_session):
        t0 = time.time()
        r = admin_session.get(f"{API}/students/lookup", params={"email": FAKE_EMAIL}, timeout=15)
        elapsed = time.time() - t0
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"
        data = r.json()
        print(f"Fake lookup elapsed={elapsed:.2f}s keys={list(data.keys())}")
        # Expect platforms present (or a dict containing them)
        platforms = ("monday", "stripe", "convertkit", "circle", "calendly")
        # Accept either top-level dict or nested 'platforms'
        root = data.get("platforms", data)
        for p in platforms:
            assert p in root, f"missing platform {p}: {list(root.keys())}"
            assert root[p].get("found") is False, f"{p} should be not found for {FAKE_EMAIL}: {root[p]}"
        assert elapsed < 15, f"negative lookup too slow: {elapsed:.2f}s"

    def test_lookup_real_email_found_on_all_platforms(self, admin_session):
        t0 = time.time()
        r = admin_session.get(f"{API}/students/lookup", params={"email": REAL_EMAIL}, timeout=30)
        elapsed = time.time() - t0
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"
        data = r.json()
        root = data.get("platforms", data)
        print(f"Real lookup elapsed={elapsed:.2f}s")
        platforms = ("monday", "stripe", "convertkit", "circle", "calendly")
        statuses = {p: root.get(p, {}).get("found") for p in platforms}
        print(f"Real lookup statuses: {statuses}")
        # Per review request, all 5 should be found
        missing = [p for p, v in statuses.items() if v is not True]
        assert not missing, f"platforms not found for {REAL_EMAIL}: {missing} | statuses={statuses}"
        assert elapsed < 20, f"positive lookup too slow: {elapsed:.2f}s"


# ---- Circle cache refresh --------------------------------------------------
class TestCircleCache:
    def test_refresh_circle_cache(self, admin_session):
        r = admin_session.post(f"{API}/students/circle-cache/refresh", timeout=120)
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"
        data = r.json()
        print(f"Circle refresh: {data}")
        assert data.get("refreshed") is True
        assert data.get("member_count", 0) >= 3000, f"member_count too low: {data.get('member_count')}"


# ---- Weekly values (for scorecard) -----------------------------------------
class TestWeeklyValues:
    def test_weekly_values_endpoint(self, admin_session):
        r = admin_session.get(f"{API}/weekly-values", timeout=30)
        assert r.status_code == 200
        wv = r.json()
        assert isinstance(wv, list)
        print(f"weekly_values count={len(wv)}")
