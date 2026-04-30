"""Tests for Iteration 9: Becky Platt, SLA notifications, CSV export."""
import os
import csv
import io
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"]
ADMIN_EMAIL = "admin@ayci.com"
ADMIN_PASSWORD = "Admin@2026"


def _session(email, password):
    s = requests.Session()
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    return s


@pytest.fixture
def admin():
    return _session(ADMIN_EMAIL, ADMIN_PASSWORD)


# ---- 1. Becky Platt linked --------------------------------------------
def test_becky_platt_team_member_exists(admin):
    r = admin.get(f"{BASE_URL}/api/team", timeout=20)
    assert r.status_code == 200
    becky = next((t for t in r.json() if t["name"] == "Becky Platt"), None)
    assert becky is not None, "Becky Platt should have a team_member row"


def test_becky_user_linked(admin):
    body = admin.get(f"{BASE_URL}/api/admin/users", timeout=20).json()
    becky_user = next(
        (u for u in body["users"] if u["name"].lower() == "becky platt"),
        None,
    )
    if becky_user is None:
        pytest.skip("No Becky Platt user account in this env")
    assert becky_user.get("team_member_id"), "Becky's user should be linked"


# ---- 2. SLA notifications --------------------------------------------
def test_sla_count_endpoint(admin):
    r = admin.get(f"{BASE_URL}/api/notifications/sla/count", timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert "unanswered_count" in body
    assert isinstance(body["unanswered_count"], int)


def test_slack_test_send_no_webhook_set_skips_gracefully(admin):
    # SLACK_WEBHOOK_URL not configured in test env → expect a graceful
    # {"sent": False, "reason": "..."} response (NOT a 500).
    r = admin.post(f"{BASE_URL}/api/notifications/slack/test", timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert "sent" in body


def test_sla_count_requires_auth():
    r = requests.get(f"{BASE_URL}/api/notifications/sla/count", timeout=10)
    assert r.status_code == 401


# ---- 3. CSV export ---------------------------------------------------
def test_csv_export_recent(admin):
    r = admin.get(
        f"{BASE_URL}/api/scorecard/export.csv?scope=recent&weeks=4", timeout=30
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers.get("content-disposition", "")
    # Parse CSV
    reader = csv.reader(io.StringIO(r.text))
    rows = list(reader)
    assert len(rows) > 1
    header = rows[0]
    assert header[0] == "Category"
    assert header[1] == "Metric"
    assert header[2] == "Format"
    assert header[3] == "Goal"
    # Should be at most 4 week-cols + 4 fixed cols
    assert len(header) <= 8


def test_csv_export_year(admin):
    r = admin.get(f"{BASE_URL}/api/scorecard/export.csv?scope=year", timeout=30)
    assert r.status_code == 200
    reader = csv.reader(io.StringIO(r.text))
    rows = list(reader)
    assert len(rows) > 1


def test_csv_export_invalid_scope(admin):
    r = admin.get(f"{BASE_URL}/api/scorecard/export.csv?scope=garbage", timeout=20)
    assert r.status_code == 400
