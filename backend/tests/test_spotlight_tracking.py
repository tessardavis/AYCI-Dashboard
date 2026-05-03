"""E2E tests for spotlight tracking API."""
import os
import sys
import httpx

BACKEND_URL = os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001"
ADMIN_EMAIL = "admin@ayci.com"
ADMIN_PW = "Admin@2026"


def _login() -> httpx.Client:
    c = httpx.Client(base_url=BACKEND_URL, timeout=60)
    r = c.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    r.raise_for_status()
    return c


def _get_session_id(c: httpx.Client) -> int:
    r = c.get("/api/spotlight/sessions", params={"limit": 1})
    r.raise_for_status()
    return r.json()["sessions"][0]["id"]


def test_upsert_and_list_records():
    c = _login()
    sid = _get_session_id(c)

    # Create
    r = c.post("/api/spotlight/records", json={
        "session_id": sid,
        "student_name": "Test Pytest User",
        "status": "spotlighted",
        "notes": "pytest note",
        "source": "manual",
    })
    r.raise_for_status()
    rec = r.json()
    assert rec["status"] == "spotlighted"
    assert rec["notes"] == "pytest note"
    assert rec["source"] == "manual"
    rec_id = rec["id"]

    # Upsert (same name → same id, new status)
    r = c.post("/api/spotlight/records", json={
        "session_id": sid,
        "student_name": "Test Pytest User",
        "status": "skipped",
    })
    r.raise_for_status()
    updated = r.json()
    assert updated["id"] == rec_id
    assert updated["status"] == "skipped"

    # List includes it
    r = c.get("/api/spotlight/records", params={"session_id": sid})
    r.raise_for_status()
    found = [x for x in r.json()["records"] if x["id"] == rec_id]
    assert len(found) == 1
    assert found[0]["status"] == "skipped"

    # Sessions endpoint should surface it as a manual record on that session
    r = c.get("/api/spotlight/sessions", params={"limit": 1})
    r.raise_for_status()
    s = r.json()["sessions"][0]
    assert any(x["id"] == rec_id for x in s.get("records") or [])

    # History includes the session
    r = c.get("/api/spotlight/history", params={"limit": 40})
    r.raise_for_status()
    groups = r.json()["sessions"]
    assert any(g["session_id"] == sid for g in groups)

    # Invalid status rejected
    r = c.post("/api/spotlight/records", json={
        "session_id": sid,
        "student_name": "Test Pytest User",
        "status": "invented_status",
    })
    assert r.status_code == 400

    # Cleanup
    r = c.delete(f"/api/spotlight/records/{rec_id}")
    r.raise_for_status()
    assert r.json()["ok"] is True

    # Delete-twice 404
    r = c.delete(f"/api/spotlight/records/{rec_id}")
    assert r.status_code == 404


def test_spotlight_counts_reflected_in_sessions():
    c = _login()
    sid = _get_session_id(c)

    # Create a spotlighted record for a name that exists in Tally list (Tammy Tran)
    r = c.post("/api/spotlight/records", json={
        "session_id": sid,
        "student_name": "Tammy Tran",
        "status": "spotlighted",
        "source": "tally",
    })
    r.raise_for_status()
    tammy_id = r.json()["id"]
    try:
        r = c.get("/api/spotlight/sessions", params={"limit": 1})
        s = r.json()["sessions"][0]
        tammy = next((st for st in s["students"] if st["name"] == "Tammy Tran"), None)
        assert tammy is not None
        assert tammy["record_status"] == "spotlighted"
        assert tammy["spotlight_count"] >= 1
    finally:
        c.delete(f"/api/spotlight/records/{tammy_id}")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
