"""Support Tickets backend tests (iteration 8)."""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ayci-dashboard.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@ayci.com"
ADMIN_PASSWORD = "Admin@2026"
COACH_EMAIL = "coach@ayci.com"
COACH_PASSWORD = "Coach@2026"


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def coach_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": COACH_EMAIL, "password": COACH_PASSWORD})
    if r.status_code != 200:
        pytest.skip("coach login failed")
    return s


@pytest.fixture(scope="module")
def created_ids():
    return []


# ------------------------------ LIST + STATS
class TestListAndStats:
    def test_list_tickets_has_73_tally(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/tickets")
        assert r.status_code == 200
        data = r.json()
        assert "tickets" in data
        tally = [t for t in data["tickets"] if t.get("source") == "tally"]
        assert len(tally) >= 73, f"expected >=73 tally tickets, got {len(tally)}"
        # Tally tickets (old, medium priority) should be overdue
        overdue_tally = [t for t in tally if t.get("overdue") is True]
        assert len(overdue_tally) >= 70, f"expected most tally tickets overdue, got {len(overdue_tally)}"
        # Ensure no _id leaks
        for t in data["tickets"][:5]:
            assert "_id" not in t

    def test_stats_shape(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/tickets/stats")
        assert r.status_code == 200
        data = r.json()
        for k in ["open", "overdue", "urgent_open", "resolved_this_week"]:
            assert k in data, f"missing {k}"
            assert isinstance(data[k], int)
        assert data["open"] >= 73


# ------------------------------ CREATE / UPDATE / DELETE
class TestCRUD:
    def test_create_manual_ticket(self, admin_session, created_ids):
        payload = {
            "student_name": "TEST_Alice",
            "student_email": "test_alice@example.com",
            "subject": "TEST_Cannot login to course portal",
            "description": "User reports 403 on login page.",
            "priority": "medium",
            "category": "tech",
        }
        r = admin_session.post(f"{BASE_URL}/api/tickets", json=payload)
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["source"] == "manual"
        assert t["status"] == "open"
        assert t["student_email"] == "test_alice@example.com"
        assert t["subject"] == payload["subject"]
        assert "updated_at" in t and t["updated_at"]
        assert "overdue" in t
        created_ids.append(t["id"])

        # GET to verify persistence
        r2 = admin_session.get(f"{BASE_URL}/api/tickets/{t['id']}")
        assert r2.status_code == 200
        assert r2.json()["subject"] == payload["subject"]

    def test_create_urgent_triggers_slack(self, admin_session, created_ids):
        payload = {
            "student_name": "TEST_UrgentBob",
            "student_email": "test_urgent_bob@example.com",
            "subject": "TEST_URGENT access issue",
            "description": "Cannot access anything",
            "priority": "urgent",
            "category": "tech",
        }
        r = admin_session.post(f"{BASE_URL}/api/tickets", json=payload)
        assert r.status_code == 200
        tid = r.json()["id"]
        created_ids.append(tid)
        # wait up to 8s for the slack background task
        sent = False
        for _ in range(16):
            time.sleep(0.5)
            fresh = admin_session.get(f"{BASE_URL}/api/tickets/{tid}").json()
            if fresh.get("slack_urgent_sent") is True:
                sent = True
                break
        assert sent, "slack_urgent_sent never became True for urgent ticket"

    def test_escalate_to_urgent_fires_slack_once(self, admin_session, created_ids):
        # create medium ticket
        payload = {
            "student_name": "TEST_EscCarol",
            "student_email": "test_esc_carol@example.com",
            "subject": "TEST_Escalation",
            "description": "starts medium",
            "priority": "medium",
            "category": "billing",
        }
        r = admin_session.post(f"{BASE_URL}/api/tickets", json=payload)
        assert r.status_code == 200
        tid = r.json()["id"]
        created_ids.append(tid)
        assert r.json().get("slack_urgent_sent") is False

        # escalate
        rp = admin_session.patch(f"{BASE_URL}/api/tickets/{tid}", json={"priority": "urgent"})
        assert rp.status_code == 200
        assert rp.json()["priority"] == "urgent"

        # wait for slack
        sent = False
        for _ in range(16):
            time.sleep(0.5)
            fresh = admin_session.get(f"{BASE_URL}/api/tickets/{tid}").json()
            if fresh.get("slack_urgent_sent") is True:
                sent = True
                break
        assert sent, "slack_urgent_sent never flipped after escalation"

        # PATCH again with unrelated change — must NOT re-send
        rp2 = admin_session.patch(f"{BASE_URL}/api/tickets/{tid}", json={"category": "tech"})
        assert rp2.status_code == 200
        time.sleep(2)
        fresh2 = admin_session.get(f"{BASE_URL}/api/tickets/{tid}").json()
        assert fresh2.get("slack_urgent_sent") is True  # still true (idempotent)

    def test_resolve_and_revert(self, admin_session, created_ids):
        payload = {
            "student_name": "TEST_ResolveDave",
            "student_email": "test_resolve_dave@example.com",
            "subject": "TEST_Resolution",
            "description": "will be resolved",
            "priority": "low",
            "category": "other",
        }
        r = admin_session.post(f"{BASE_URL}/api/tickets", json=payload)
        tid = r.json()["id"]
        created_ids.append(tid)
        # resolve
        rp = admin_session.patch(f"{BASE_URL}/api/tickets/{tid}", json={"status": "resolved"})
        assert rp.status_code == 200
        assert rp.json()["status"] == "resolved"
        assert rp.json()["resolved_at"] is not None
        # revert
        rp2 = admin_session.patch(f"{BASE_URL}/api/tickets/{tid}", json={"status": "open"})
        assert rp2.status_code == 200
        assert rp2.json()["status"] == "open"
        assert rp2.json()["resolved_at"] is None


# ------------------------------ FILTERS + SEARCH
class TestFilters:
    def test_filter_by_status_resolved(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/tickets", params={"status": "resolved"})
        assert r.status_code == 200
        for t in r.json()["tickets"]:
            assert t["status"] == "resolved"

    def test_filter_by_priority_urgent(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/tickets", params={"priority": "urgent"})
        assert r.status_code == 200
        for t in r.json()["tickets"]:
            assert t["priority"] == "urgent"

    def test_search_query(self, admin_session):
        # Create a ticket with a unique term
        payload = {
            "student_name": "TEST_SearchMary",
            "student_email": "test_search_mary@example.com",
            "subject": "TEST_SEARCHTOKEN_xyzzy123 login fails",
            "description": "login broken",
            "priority": "low",
            "category": "tech",
        }
        cr = admin_session.post(f"{BASE_URL}/api/tickets", json=payload)
        tid = cr.json()["id"]
        r = admin_session.get(f"{BASE_URL}/api/tickets", params={"q": "xyzzy123"})
        assert r.status_code == 200
        found = [t for t in r.json()["tickets"] if t["id"] == tid]
        assert len(found) == 1
        # cleanup
        admin_session.delete(f"{BASE_URL}/api/tickets/{tid}")


# ------------------------------ NOTES
class TestNotes:
    def test_add_note(self, admin_session, created_ids):
        payload = {
            "student_name": "TEST_NoteNed",
            "student_email": "test_note_ned@example.com",
            "subject": "TEST_Note thread",
            "description": "needs a note",
            "priority": "low",
            "category": "other",
        }
        r = admin_session.post(f"{BASE_URL}/api/tickets", json=payload)
        tid = r.json()["id"]
        created_ids.append(tid)
        rn = admin_session.post(f"{BASE_URL}/api/tickets/{tid}/notes", json={"body": "Test internal note", "internal": True})
        assert rn.status_code == 200
        t = rn.json()
        assert len(t["notes"]) == 1
        assert t["notes"][0]["body"] == "Test internal note"
        assert t["notes"][0]["author_name"]


# ------------------------------ TALLY SYNC + WEBHOOK
class TestTally:
    def test_sync_idempotent(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/tickets/tally/sync")
        assert r.status_code == 200
        data = r.json()
        assert "inserted" in data and "scanned" in data
        # Second call should insert 0
        r2 = admin_session.post(f"{BASE_URL}/api/tickets/tally/sync")
        assert r2.status_code == 200
        assert r2.json()["inserted"] == 0

    def test_webhook_rejects_wrong_form_id(self):
        payload = {"data": {"formId": "WRONGID", "submissionId": "test_wrong_1", "fields": []}}
        r = requests.post(f"{BASE_URL}/api/tickets/tally/webhook", json=payload)
        assert r.status_code == 200
        assert r.json().get("ignored") is True

    def test_webhook_creates_and_is_idempotent(self, admin_session):
        sub_id = f"test_webhook_sub_{int(time.time())}"
        payload = {
            "data": {
                "formId": "D4BW1N",
                "submissionId": sub_id,
                "createdAt": "2026-01-15T10:00:00Z",
                "fields": [
                    {"key": "62aD7J", "value": "TEST_WebhookWally"},
                    {"key": "726XWR", "value": "test_webhook_wally@example.com"},
                    {"key": "bxbZ7Z", "value": "Need help with login via webhook"},
                ],
            }
        }
        r = requests.post(f"{BASE_URL}/api/tickets/tally/webhook", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        tid = body["ticket_id"]

        # idempotent retry
        r2 = requests.post(f"{BASE_URL}/api/tickets/tally/webhook", json=payload)
        assert r2.status_code == 200
        assert r2.json().get("ignored") is True

        # cleanup
        admin_session.delete(f"{BASE_URL}/api/tickets/{tid}")


# ------------------------------ PERMISSIONS
class TestPermissions:
    def test_coach_no_tickets_board_403(self, coach_session):
        r = coach_session.get(f"{BASE_URL}/api/tickets")
        assert r.status_code == 403, f"expected 403 for coach, got {r.status_code}"
        r2 = coach_session.get(f"{BASE_URL}/api/tickets/stats")
        assert r2.status_code == 403


# ------------------------------ CLEANUP
def test_zz_cleanup(admin_session, created_ids):
    for tid in created_ids:
        admin_session.delete(f"{BASE_URL}/api/tickets/{tid}")
    # Verify 73 tally remain
    r = admin_session.get(f"{BASE_URL}/api/tickets")
    tally = [t for t in r.json()["tickets"] if t.get("source") == "tally"]
    assert len(tally) >= 73
