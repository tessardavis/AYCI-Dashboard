"""Iteration 3 tests - cohort summary (Kit tags + intros) + drive summary."""
import os
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin@ayci.com"
ADMIN_PASS = "Admin@2026"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
               timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return s


# --- Cohort summary (ConvertKit tags + intros) ------------------------------
def test_cohort_summary_april26(client):
    r = client.get(f"{BASE_URL}/api/cohorts/summary",
                   params={"cohort": "April 26"}, timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    # totals.source = convertkit
    assert data["totals"]["source"] == "convertkit", f"source={data['totals']['source']}"
    # new ~124, legacy ~139 (±10 tolerance)
    new = data["totals"]["new"]
    legacy = data["totals"]["legacy"]
    print(f"new={new} legacy={legacy} total={data['totals']['students']}")
    assert 100 <= new <= 150, f"expected new ~124, got {new}"
    assert 115 <= legacy <= 160, f"expected legacy ~139, got {legacy}"
    # Circle intros present
    intros = data["circle"]["intros"]
    assert intros is not None
    assert "students_posted" in intros
    assert "coverage_percent" in intros
    assert intros["space_id"] == 2529515
    print(f"intros: posted={intros['students_posted']}/{intros['students_total']}, "
          f"coverage={intros['coverage_percent']}%, "
          f"posts_total={intros['posts_total']}, err={intros.get('error')}")
    # Kit block
    assert data["kit"]["new_tag_id"] == 14407610
    assert data["kit"]["legacy_tag_id"] == 14407628


# --- Drive summary ---------------------------------------------------------
def test_drive_summary_vip_student(client):
    """Anna Walsh is VIP tier - should find a doc (even if we can't read it)."""
    r = client.get(f"{BASE_URL}/api/students/drive-summary",
                   params={"email": "anna.swalsh@btinternet.com",
                           "name": "Anna Walsh"},
                   timeout=90)
    assert r.status_code == 200, r.text
    data = r.json()
    print(f"drive-summary Anna: found={data.get('found')} err={data.get('error')}")
    assert data["found"] is True, f"expected found=true, got {data}"
    assert data.get("file") is not None
    assert data["file"].get("web_view_link"), "web_view_link missing"
    # Either summary or a helpful share-with-service-account hint
    has_summary = bool(data.get("summary"))
    has_hint = bool(data.get("error")) and "ayci-drive-reader" in (data.get("error") or "")
    assert has_summary or has_hint, f"expected summary or share-hint, got {data}"


def test_drive_summary_unknown_name(client):
    """Random unknown student → found=false gracefully."""
    r = client.get(f"{BASE_URL}/api/students/drive-summary",
                   params={"email": "nobody-xyz-qqq@example.com",
                           "name": "Zzzzzz Nobodymatch"},
                   timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["found"] is False, data
    assert data.get("candidates_scanned", 0) > 0, "should have scanned some files"


def test_drive_summary_requires_auth():
    r = requests.get(f"{BASE_URL}/api/students/drive-summary",
                     params={"email": "a@b.com", "name": "X Y"}, timeout=20)
    assert r.status_code == 401
