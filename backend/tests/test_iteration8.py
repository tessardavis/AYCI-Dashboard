"""Tests for Iteration 8: metric reorder, per-user rock edit, quarter archiving."""
import os
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"]
ADMIN_EMAIL = "admin@ayci.com"
ADMIN_PASSWORD = "Admin@2026"
ARUB_EMAIL = "arub@medicalinterviewprep.com"
ARUB_PASSWORD = "Welcome@AYCI2026"


def _session(email, password):
    s = requests.Session()
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=20,
    )
    assert r.status_code == 200, f"Login failed: {r.text}"
    return s


@pytest.fixture
def admin():
    return _session(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture
def arub():
    return _session(ARUB_EMAIL, ARUB_PASSWORD)


# ---------------- Task 1: metric reorder ----------------
def test_metric_reorder_admin_swap(admin):
    r = admin.get(f"{BASE_URL}/api/metrics", timeout=20)
    assert r.status_code == 200
    metrics = r.json()
    growth = sorted(
        [m for m in metrics if m["category"] == "GROWTH + INTEREST"],
        key=lambda m: m["order"],
    )
    assert len(growth) >= 2
    first, second = growth[0], growth[1]
    payload = {"order": [
        {"id": first["id"], "order": second["order"]},
        {"id": second["id"], "order": first["order"]},
    ]}
    r = admin.patch(f"{BASE_URL}/api/metrics/reorder", json=payload, timeout=20)
    assert r.status_code == 200
    assert r.json()["updated"] == 2
    # Verify swap
    r2 = admin.get(f"{BASE_URL}/api/metrics", timeout=20)
    swapped = {m["id"]: m["order"] for m in r2.json()}
    assert swapped[first["id"]] == second["order"]
    assert swapped[second["id"]] == first["order"]
    # Swap back
    admin.patch(
        f"{BASE_URL}/api/metrics/reorder",
        json={"order": [
            {"id": first["id"], "order": first["order"]},
            {"id": second["id"], "order": second["order"]},
        ]},
        timeout=20,
    )


def test_metric_reorder_non_admin_blocked(arub):
    r = arub.patch(
        f"{BASE_URL}/api/metrics/reorder",
        json={"order": []},
        timeout=20,
    )
    assert r.status_code == 403


# ---------------- Task 2: per-user rock edit ----------------
def test_auth_me_includes_team_member_id(arub):
    r = arub.get(f"{BASE_URL}/api/auth/me", timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert "team_member_id" in body
    assert body["team_member_id"], "Arub should be auto-linked to a team_member"


def test_arub_edits_own_rock_success(arub):
    me = arub.get(f"{BASE_URL}/api/auth/me", timeout=20).json()
    tm_id = me["team_member_id"]
    rocks = arub.get(f"{BASE_URL}/api/rocks", timeout=20).json()
    own = next((r for r in rocks if r["owner_id"] == tm_id), None)
    assert own is not None, "Arub should have at least one rock"
    r = arub.patch(
        f"{BASE_URL}/api/rocks/{own['id']}",
        json={"notes": "iteration-8 self-edit test"},
        timeout=20,
    )
    assert r.status_code == 200
    assert r.json()["notes"] == "iteration-8 self-edit test"


def test_arub_cannot_edit_other_rock(arub):
    me = arub.get(f"{BASE_URL}/api/auth/me", timeout=20).json()
    tm_id = me["team_member_id"]
    rocks = arub.get(f"{BASE_URL}/api/rocks", timeout=20).json()
    other = next((r for r in rocks if r["owner_id"] != tm_id), None)
    assert other is not None
    r = arub.patch(
        f"{BASE_URL}/api/rocks/{other['id']}",
        json={"notes": "should fail"},
        timeout=20,
    )
    assert r.status_code == 403


def test_arub_cannot_reassign_or_move_own_rock(arub):
    me = arub.get(f"{BASE_URL}/api/auth/me", timeout=20).json()
    tm_id = me["team_member_id"]
    rocks = arub.get(f"{BASE_URL}/api/rocks", timeout=20).json()
    own = next((r for r in rocks if r["owner_id"] == tm_id), None)
    assert own is not None
    # Attempt to reassign owner_id to another team member
    r = arub.patch(
        f"{BASE_URL}/api/rocks/{own['id']}",
        json={"owner_id": "some-other-tm-id", "notes": "boundary test"},
        timeout=20,
    )
    assert r.status_code == 200
    # owner_id change should be silently stripped
    assert r.json()["owner_id"] == tm_id


def test_admin_can_edit_any_rock(admin):
    rocks = admin.get(f"{BASE_URL}/api/rocks", timeout=20).json()
    assert len(rocks) > 0
    r = admin.patch(
        f"{BASE_URL}/api/rocks/{rocks[0]['id']}",
        json={"notes": "admin edit"},
        timeout=20,
    )
    assert r.status_code == 200


def test_admin_users_exposes_team_members_and_link(admin):
    r = admin.get(f"{BASE_URL}/api/admin/users", timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert "team_members" in body and isinstance(body["team_members"], list)
    assert len(body["team_members"]) > 0
    # At least one user has team_member_id set (the auto-link migration ran)
    assert any(u.get("team_member_id") for u in body["users"])


def test_admin_can_link_and_unlink_team_member(admin):
    body = admin.get(f"{BASE_URL}/api/admin/users", timeout=20).json()
    unlinked = next(
        (u for u in body["users"] if u["role"] != "admin" and not u.get("team_member_id")),
        None,
    )
    if unlinked is None:
        pytest.skip("No unlinked user available to test with")
    tm = body["team_members"][0]
    # Link
    r = admin.patch(
        f"{BASE_URL}/api/admin/users/{unlinked['id']}",
        json={"team_member_id": tm["id"]},
        timeout=20,
    )
    assert r.status_code == 200
    assert r.json()["team_member_id"] == tm["id"]
    # Unlink (empty string)
    r = admin.patch(
        f"{BASE_URL}/api/admin/users/{unlinked['id']}",
        json={"team_member_id": ""},
        timeout=20,
    )
    assert r.status_code == 200
    assert r.json().get("team_member_id") is None


def test_admin_rejects_unknown_team_member_id(admin):
    body = admin.get(f"{BASE_URL}/api/admin/users", timeout=20).json()
    victim = body["users"][0]
    r = admin.patch(
        f"{BASE_URL}/api/admin/users/{victim['id']}",
        json={"team_member_id": "nonsense-id-xyz"},
        timeout=20,
    )
    assert r.status_code == 400


# ---------------- Task 3: quarter archiving ----------------
def test_rocks_quarters_has_active_field(admin):
    r = admin.get(f"{BASE_URL}/api/rocks/quarters", timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert "quarters" in body and "active" in body
    assert isinstance(body["quarters"], list)


def test_set_active_quarter_admin(admin):
    qs = admin.get(f"{BASE_URL}/api/rocks/quarters", timeout=20).json()
    assert len(qs["quarters"]) > 0
    target = qs["quarters"][0]
    r = admin.put(
        f"{BASE_URL}/api/rocks/active-quarter",
        json={"quarter": target},
        timeout=20,
    )
    assert r.status_code == 200
    assert r.json()["active"] == target


def test_set_active_quarter_non_admin_blocked(arub):
    r = arub.put(
        f"{BASE_URL}/api/rocks/active-quarter",
        json={"quarter": "Q2 2026"},
        timeout=20,
    )
    assert r.status_code == 403


def test_archived_quarter_blocks_non_admin_edit(admin, arub):
    # 1. Set active to a fake quarter ('Q99 9999' — no rocks there)
    admin.put(
        f"{BASE_URL}/api/rocks/active-quarter",
        json={"quarter": "Q99 9999"},
        timeout=20,
    )
    try:
        me = arub.get(f"{BASE_URL}/api/auth/me", timeout=20).json()
        tm_id = me["team_member_id"]
        rocks = arub.get(f"{BASE_URL}/api/rocks", timeout=20).json()
        own = next((r for r in rocks if r["owner_id"] == tm_id), None)
        assert own is not None
        # All rocks now in archived quarters → Arub gets 403
        r = arub.patch(
            f"{BASE_URL}/api/rocks/{own['id']}",
            json={"notes": "archived-should-fail"},
            timeout=20,
        )
        assert r.status_code == 403
        # Admin can still edit
        r = admin.patch(
            f"{BASE_URL}/api/rocks/{own['id']}",
            json={"notes": "admin edits archived"},
            timeout=20,
        )
        assert r.status_code == 200
    finally:
        # Restore active quarter to Q2 2026
        admin.put(
            f"{BASE_URL}/api/rocks/active-quarter",
            json={"quarter": "Q2 2026"},
            timeout=20,
        )
