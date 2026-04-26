"""
Iteration 4 backend tests.

Coverage:
  - Auth (login → session cookies)
  - GET /api/students/name-search (autocomplete)
  - GET /api/launches  (returns launches with `code` and `phases`)
  - GET /api/launches/{id}/registrations   (Kit per-source webinar reg tags)
  - GET /api/launches/{id}/sales           (Stripe charges in window, by product)
  - GET /api/launches/{id}/comparison?n_previous=2  (overlay vs prev 2 launches)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ayci-dashboard.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@ayci.com"
ADMIN_PASSWORD = "Admin@2026"


# ---------------------------------------------------------------- Fixtures
@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code} {r.text[:200]}")
    return s


@pytest.fixture(scope="session")
def launches(session):
    r = session.get(f"{BASE_URL}/api/launches", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list) and len(data) > 0
    return data


@pytest.fixture(scope="session")
def april_launch(launches):
    """Find April 2026 launch (code APR-26)."""
    for L in launches:
        if (L.get("code") or "").upper() == "APR-26":
            return L
    pytest.skip("APR-26 launch not found")


# ---------------------------------------------------------------- Auth
class TestAuth:
    def test_login_sets_session(self, session):
        r = session.get(f"{BASE_URL}/api/auth/me", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body.get("email") == ADMIN_EMAIL


# ---------------------------------------------------------------- Name search
class TestNameSearch:
    def test_name_search_anna(self, session):
        r = session.get(
            f"{BASE_URL}/api/students/name-search",
            params={"q": "anna", "limit": 5},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        results = r.json()
        assert isinstance(results, list)
        assert len(results) >= 1, "Expected at least 1 anna match"
        first = results[0]
        # Schema check
        for key in ("name", "email", "avatar_url", "match_score"):
            assert key in first, f"Missing '{key}' in {first}"
        assert isinstance(first["match_score"], (int, float))

    def test_name_search_anna_walsh_specific(self, session):
        r = session.get(
            f"{BASE_URL}/api/students/name-search",
            params={"q": "anna walsh", "limit": 5},
            timeout=30,
        )
        assert r.status_code == 200
        results = r.json()
        emails = [(x.get("email") or "").lower() for x in results]
        assert any("anna" in e for e in emails), f"No anna in results: {emails}"

    def test_name_search_short_query(self, session):
        # query <2 chars → empty list
        r = session.get(
            f"{BASE_URL}/api/students/name-search",
            params={"q": "a"},
            timeout=15,
        )
        assert r.status_code == 200
        assert r.json() == []

    def test_name_search_unauth(self):
        r = requests.get(
            f"{BASE_URL}/api/students/name-search",
            params={"q": "anna"},
            timeout=15,
        )
        assert r.status_code in (401, 403)


# ---------------------------------------------------------------- Launches
class TestLaunchesList:
    def test_launches_have_code_and_phases(self, launches):
        # At least one launch must have code APR-26 with 7 phases
        apr = next((L for L in launches if (L.get("code") or "").upper() == "APR-26"), None)
        assert apr is not None, "APR-26 not in launches list"
        phases = apr.get("phases") or {}
        # phases is a dict with 7 keys, each having start/end
        # Possible shapes: dict of {phase_name: {start, end}} OR a list
        if isinstance(phases, dict):
            assert len(phases) >= 7, f"Expected >=7 phases, got {len(phases)}: {list(phases.keys())}"
            for name, phase in phases.items():
                assert isinstance(phase, dict)
                assert "start" in phase and "end" in phase, f"Phase {name} missing start/end"
        elif isinstance(phases, list):
            assert len(phases) >= 7
            for phase in phases:
                assert "start" in phase and "end" in phase
        else:
            pytest.fail(f"Unexpected phases type: {type(phases)}")


class TestLaunchRegistrations:
    def test_registrations_for_apr26(self, session, april_launch):
        r = session.get(
            f"{BASE_URL}/api/launches/{april_launch['id']}/registrations",
            timeout=120,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "total" in body and "by_source" in body and "by_day" in body
        # Per review-request: total should be > 1000
        assert body["total"] > 1000, f"Expected total>1000, got {body['total']}"
        assert isinstance(body["by_source"], list) and len(body["by_source"]) > 0
        for entry in body["by_source"]:
            assert "source" in entry and "count" in entry
        assert isinstance(body["by_day"], list)
        if body["by_day"]:
            row = body["by_day"][0]
            assert "date" in row and "total" in row


class TestLaunchSales:
    def test_sales_for_apr26(self, session, april_launch):
        r = session.get(
            f"{BASE_URL}/api/launches/{april_launch['id']}/sales",
            timeout=120,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "total_amount_gbp" in body
        assert body["total_amount_gbp"] > 0, f"Expected total_amount_gbp>0, got {body['total_amount_gbp']}"
        assert "by_product" in body and isinstance(body["by_product"], list)
        assert len(body["by_product"]) > 0
        for entry in body["by_product"]:
            assert "product" in entry and "amount_gbp" in entry and "count" in entry
        assert "by_day" in body and isinstance(body["by_day"], list)


class TestLaunchComparison:
    def test_comparison_apr26_vs_prev_2(self, session, april_launch):
        r = session.get(
            f"{BASE_URL}/api/launches/{april_launch['id']}/comparison",
            params={"n_previous": 2},
            timeout=180,  # this endpoint is slow (60-120s)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "current" in body and "previous" in body
        assert isinstance(body["previous"], list)
        assert len(body["previous"]) == 2, f"Expected 2 previous launches, got {len(body['previous'])}"
        # Each previous entry should have aligned series
        for entry in body["previous"]:
            assert "id" in entry and "code" in entry and "name" in entry
            assert "registrations_aligned" in entry
            assert "sales_aligned" in entry
            assert isinstance(entry["registrations_aligned"], list)
            assert isinstance(entry["sales_aligned"], list)
            # Each aligned row has day_offset
            for row in entry["registrations_aligned"][:3]:
                assert "day_offset" in row
            for row in entry["sales_aligned"][:3]:
                assert "day_offset" in row
        # Verify codes are FEB-26 and NOV-25 per review-request
        codes = sorted([(e.get("code") or "").upper() for e in body["previous"]])
        assert "FEB-26" in codes, f"FEB-26 missing from previous: {codes}"
        assert "NOV-25" in codes, f"NOV-25 missing from previous: {codes}"
