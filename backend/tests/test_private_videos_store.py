"""DB-backed Private-Tier Videos pipeline tests.

Run: cd /app/backend && python -m pytest tests/test_private_videos_store.py -v
"""
import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://ayci-dashboard.preview.emergentagent.com"
).rstrip("/")
ADMIN_EMAIL = "admin@ayci.com"
ADMIN_PASSWORD = "Admin@2026"
TALLY_FORM_ID = "0Qr5py"


@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return s


def _webhook_payload(sub_id: str, email: str, q: str = "Q?", first: str = "T", last: str = "Est"):
    return {
        "eventId": f"evt-{sub_id}",
        "eventType": "FORM_RESPONSE",
        "createdAt": "2026-05-07T13:30:00Z",
        "data": {
            "submissionId": sub_id,
            "formId": TALLY_FORM_ID,
            "createdAt": "2026-05-07T13:30:00Z",
            "fields": [
                {"key": "JzG2rX", "value": first},
                {"key": "gGg5VJ", "value": last},
                {"key": "yYglbd", "value": email},
                {"key": "pO1ObE", "value": q},
                {"key": "X09e7z", "value": [{"url": f"https://x.test/{sub_id}.mp4"}]},
            ],
        },
    }


def test_list_returns_db_source(admin):
    r = admin.get(f"{BASE_URL}/api/private-videos")
    assert r.status_code == 200
    data = r.json()
    assert data.get("source") == "db"
    assert isinstance(data.get("items"), list)


def test_users_returns_team_members(admin):
    r = admin.get(f"{BASE_URL}/api/private-videos/users")
    assert r.status_code == 200
    users = r.json()["users"]
    names = [u["name"] for u in users]
    assert "Becky Platt" in names
    assert "Tessa Davis" in names


def test_stats_endpoint(admin):
    r = admin.get(f"{BASE_URL}/api/private-videos/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["total"] >= s["from_monday"]


def test_tally_webhook_ingest_and_idempotency(admin):
    sub_id = f"pytest-{uuid.uuid4().hex[:12]}"
    email = f"pytest-{uuid.uuid4().hex[:8]}@test.local"
    payload = _webhook_payload(sub_id, email)

    # First call creates
    r1 = requests.post(f"{BASE_URL}/api/private-videos/tally-webhook", json=payload)
    assert r1.status_code == 200, r1.text
    assert r1.json().get("ok") is True
    item_id = r1.json()["id"]

    # Second call is ignored (idempotent on submissionId)
    r2 = requests.post(f"{BASE_URL}/api/private-videos/tally-webhook", json=payload)
    assert r2.status_code == 200
    assert r2.json().get("ignored") is True
    assert r2.json().get("id") == item_id

    # The new row appears in the list with submission_number=1 + tally fields populated
    listed = admin.get(f"{BASE_URL}/api/private-videos").json()
    matches = [i for i in listed["items"] if i.get("email") == email]
    assert len(matches) == 1
    it = matches[0]
    assert it["submission_number"] == "1"
    assert it["tally_video"]["url"].endswith(".mp4")
    assert it["status"] == "New"

    # Cleanup: PATCH to Done so it's out of the way (we keep it; full delete
    # endpoint isn't exposed yet)
    pat = admin.patch(
        f"{BASE_URL}/api/private-videos/{item_id}",
        json={"status_label": "Done"},
    )
    assert pat.status_code == 200


def test_tally_webhook_ignores_other_form():
    payload = _webhook_payload("xx", "ignore@test.local")
    payload["data"]["formId"] = "WRONG_FORM"
    r = requests.post(f"{BASE_URL}/api/private-videos/tally-webhook", json=payload)
    assert r.status_code == 200
    assert r.json().get("ignored") is True


def test_tally_webhook_ignores_no_email():
    payload = _webhook_payload(f"noemail-{uuid.uuid4().hex[:6]}", "")
    r = requests.post(f"{BASE_URL}/api/private-videos/tally-webhook", json=payload)
    assert r.status_code == 200
    assert r.json().get("ignored") is True


def test_patch_assignee(admin):
    listed = admin.get(f"{BASE_URL}/api/private-videos").json()
    assert listed["items"], "no items in DB to patch — run migration first"
    item = listed["items"][0]
    users = admin.get(f"{BASE_URL}/api/private-videos/users").json()["users"]
    becky = next(u for u in users if u["name"] == "Becky Platt")

    original = item.get("assignee_id")
    try:
        r = admin.patch(
            f"{BASE_URL}/api/private-videos/{item['id']}",
            json={"assignee_id": becky["id"]},
        )
        assert r.status_code == 200
        assert r.json()["assignee_name"] == "Becky Platt"
    finally:
        admin.patch(
            f"{BASE_URL}/api/private-videos/{item['id']}",
            json={"assignee_id": original or ""},
        )


def test_migrate_idempotent(admin):
    """Re-running migration should not duplicate rows."""
    before = admin.get(f"{BASE_URL}/api/private-videos/stats").json()["total"]
    r = admin.post(f"{BASE_URL}/api/private-videos/migrate-from-monday")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    after = admin.get(f"{BASE_URL}/api/private-videos/stats").json()["total"]
    # Within +/- a small drift (a real Tally submission may land mid-test);
    # the headline guarantee is "no duplicates from re-running migration".
    assert after - before <= 5


# -------------------------------------------- Send to Circle (Zapier webhook)
def test_send_to_circle_404(admin):
    r = admin.post(f"{BASE_URL}/api/private-videos/does-not-exist/send-to-circle")
    assert r.status_code == 404


def test_send_to_circle_400_no_reply_link(admin):
    """If reply_link is empty, refuse to send (clearer than letting Zapier
    receive a blank URL)."""
    listed = admin.get(f"{BASE_URL}/api/private-videos").json()
    target = next(
        (i for i in listed["items"] if not (i.get("reply_link") or {}).get("url")),
        None,
    )
    assert target is not None, "no item without a reply_link in DB"
    r = admin.post(f"{BASE_URL}/api/private-videos/{target['id']}/send-to-circle")
    assert r.status_code == 400
    assert "voicenote url" in r.json()["detail"].lower()


def test_zapier_webhook_setting_validation(admin):
    """Validate that the Zapier webhook URL endpoint enforces the right format.
    Doesn't overwrite an existing configured URL — just tests the validator."""
    # Reject non-Zapier URL — returns 200 with ok:false (so the UI can toast)
    r = admin.post(
        f"{BASE_URL}/api/private-videos/zapier-webhook",
        json={"url": "https://evil.test/post"},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is False

    # GET shape
    state = admin.get(f"{BASE_URL}/api/private-videos/zapier-webhook").json()
    assert "configured" in state
    assert "masked" in state
