"""Bulk close + Gmail label-routing helper tests.

Run: cd /app/backend && python -m pytest tests/test_tickets_bulk_close.py -v
"""
import os
import sys
import uuid

import pytest
import requests

# Make backend root importable for the unit-test on label helpers.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://ayci-dashboard.preview.emergentagent.com",
).rstrip("/")
ADMIN_EMAIL = "admin@ayci.com"
ADMIN_PASSWORD = "Admin@2026"


@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return s


def _create_ticket(admin) -> str:
    payload = {
        "student_name": "Bulk Close Test",
        "student_email": f"bulkclose+{uuid.uuid4().hex[:8]}@example.com",
        "subject": "Bulk close test",
        "description": "Created by automated test",
        "priority": "medium",
        "category": "other",
    }
    r = admin.post(f"{BASE_URL}/api/tickets", json=payload)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_bulk_close_validates_empty_list(admin):
    r = admin.post(f"{BASE_URL}/api/tickets/bulk-close", json={"ids": []})
    assert r.status_code == 422


def test_bulk_close_unknown_ids_is_noop(admin):
    r = admin.post(
        f"{BASE_URL}/api/tickets/bulk-close",
        json={"ids": [f"__missing_{uuid.uuid4().hex}__"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["closed"] == 0


def test_bulk_close_closes_tickets_and_is_idempotent(admin):
    ids = [_create_ticket(admin) for _ in range(3)]
    try:
        r = admin.post(f"{BASE_URL}/api/tickets/bulk-close", json={"ids": ids})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["closed"] == 3
        assert body["requested"] == 3

        # Verify state on each ticket
        for tid in ids:
            t = admin.get(f"{BASE_URL}/api/tickets/{tid}").json()
            assert t["status"] == "closed"
            assert t["resolved_at"]

        # Idempotent: running again on already-closed tickets reports 0
        r2 = admin.post(f"{BASE_URL}/api/tickets/bulk-close", json={"ids": ids})
        assert r2.status_code == 200
        assert r2.json()["closed"] == 0
    finally:
        for tid in ids:
            admin.delete(f"{BASE_URL}/api/tickets/{tid}")


# ---------------------- Gmail label-routing helpers (unit) ----------------------
def test_resolve_label_assignee_matches_first_name():
    from gmail_sync import _resolve_label_assignee

    routing = {"coralie": "tm-coralie-id", "arub": "tm-arub-id"}
    label_names = {
        "Label_1": "INBOX",
        "Label_2": "coralie",
        "Label_3": "Important",
    }
    # message tagged `coralie` → routes to Coralie
    assert _resolve_label_assignee(["Label_1", "Label_2"], label_names, routing) == "tm-coralie-id"


def test_resolve_label_assignee_handles_nested_label():
    from gmail_sync import _resolve_label_assignee

    routing = {"coralie": "tm-coralie-id"}
    label_names = {"Label_9": "Support/Coralie"}
    assert _resolve_label_assignee(["Label_9"], label_names, routing) == "tm-coralie-id"


def test_resolve_label_assignee_no_match_returns_none():
    from gmail_sync import _resolve_label_assignee

    routing = {"coralie": "tm-coralie-id"}
    label_names = {"Label_1": "INBOX", "Label_2": "Important"}
    assert _resolve_label_assignee(["Label_1", "Label_2"], label_names, routing) is None


def test_resolve_label_assignee_empty_inputs():
    from gmail_sync import _resolve_label_assignee

    assert _resolve_label_assignee([], {}, {}) is None
    assert _resolve_label_assignee(None, {}, {"coralie": "x"}) is None
