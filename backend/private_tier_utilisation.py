"""
Private Tier Utilisation tracker.

For Private Plus and VIP students with an upcoming interview in the next
N days (default 14), check whether they're on track with their video
submissions and 1:1 calls — and surface the rest as a chase list.

Allowances (per tier, defined by the team):
  - Private Plus: 15 video submissions + 1 × 1:1 call
  - VIP:           30 video submissions + 4 × 30-min calls + 1 × 60-min call
                                         (we treat the 60-min as a 5th call)

On-track thresholds:
  - Private Plus: ≥ 50% of video allowance (≥8 videos) AND ≥ 1 call → ✅
  - VIP:           ≥ 2 calls AND ≥ 1/3 of video allowance (≥10 videos) → ✅

Calls are filtered to the four AYCI 1:1 / VIP / Bonus / Mock event types so
group-coaching events don't accidentally count.
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone, date
from typing import Optional

import httpx

from connectors import (
    MONDAY_URL,
    _monday_headers,
    CALENDLY_BASE,
    _calendly_headers,
    TIMEOUT,
)


# Same constants as upcoming_interviews
ACADEMY_MEMBERS_BOARD_ID = 1956295952
COL_INTERVIEW_DATE = "date_mkr7rdv7"
COL_TIER = "dropdown_mkqxgqbq"
COL_EMAIL = "email_mkqxv0j0"
COL_VIDEOS_SUBMITTED = "numeric_mkxfq65c"  # Number column "Videos submitted"
COL_NAME = "name"
COL_SPECIALITY = "color_mkqx20m0"
COL_HOSPITAL = "color_mkqxckby"
COL_INTERVIEW_TYPE = "color_mkr7wahg"  # Status: "Locum" / "Substantive"

# Tiers we care about
PRIVATE_PLUS_LABELS = {"Academy Private Plus", "Upgrade Private Plus", "Silver", "Gold"}
VIP_LABELS = {"VIP", "Platinum"}

# Allowances
ALLOWANCES = {
    "Private Plus": {"videos": 15, "calls": 1},
    "VIP":          {"videos": 30, "calls": 5},
}

# Thresholds
THRESHOLDS = {
    "Private Plus": {"min_videos_pct": 0.50, "min_calls": 1, "logic": "and"},
    "VIP":          {"min_videos_pct": 1 / 3, "min_calls": 2, "logic": "and"},
}

# Calendly event-type names that count as "private" 1:1 calls
PRIVATE_CALL_NAMES = ["AYCI 1:1", "AYCI VIP", "AYCI Bonus Call", "AYCI Mock"]


def _normalise_tier(tier_text: str) -> Optional[str]:
    if not tier_text:
        return None
    t = tier_text.strip()
    if t in VIP_LABELS:
        return "VIP"
    if t in PRIVATE_PLUS_LABELS:
        return "Private Plus"
    return None


# ---------- Monday: students with upcoming interview --------------------------

async def _fetch_private_tier_with_interviews(days: int) -> list[dict]:
    """Pull Academy Members rows whose Tier is Private Plus / VIP and whose
    Interview Date is in [today, today + days]."""
    today = datetime.now(timezone.utc).date()
    cutoff = (today + timedelta(days=days)).isoformat()

    q = """
    query ($boardId: ID!, $cursor: String) {
      boards(ids: [$boardId]) {
        items_page(limit: 200, cursor: $cursor) {
          cursor
          items {
            id name url
            column_values(ids: ["%s","%s","%s","%s","%s","%s","%s"]) {
              id text
            }
          }
        }
      }
    }
    """ % (
        COL_INTERVIEW_DATE, COL_TIER, COL_EMAIL,
        COL_VIDEOS_SUBMITTED, COL_SPECIALITY, COL_HOSPITAL, COL_INTERVIEW_TYPE,
    )

    items: list[dict] = []
    cursor: Optional[str] = None
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        while True:
            r = await c.post(
                MONDAY_URL,
                headers={**_monday_headers(), "Content-Type": "application/json"},
                json={"query": q, "variables": {"boardId": str(ACADEMY_MEMBERS_BOARD_ID), "cursor": cursor}},
            )
            r.raise_for_status()
            body = r.json()
            page = (body.get("data", {}).get("boards") or [{}])[0].get("items_page") or {}
            items.extend(page.get("items") or [])
            cursor = page.get("cursor")
            if not cursor:
                break

    out: list[dict] = []
    for it in items:
        cvs = {cv.get("id"): (cv.get("text") or "").strip() for cv in (it.get("column_values") or [])}
        d = cvs.get(COL_INTERVIEW_DATE) or ""
        if not d:
            continue
        try:
            ds = d.split(" ")[0]
            di = datetime.fromisoformat(ds).date()
        except ValueError:
            continue
        if di < today or di.isoformat() > cutoff:
            continue
        tier = _normalise_tier(cvs.get(COL_TIER, ""))
        if not tier:
            continue
        try:
            videos = int(cvs.get(COL_VIDEOS_SUBMITTED, "0") or 0)
        except (ValueError, TypeError):
            videos = 0
        out.append({
            "monday_id": it.get("id"),
            "monday_url": it.get("url"),
            "name": it.get("name"),
            "email": (cvs.get(COL_EMAIL) or "").lower().strip(),
            "tier": tier,
            "tier_raw": cvs.get(COL_TIER, ""),
            "interview_date": di.isoformat(),
            "days_until": (di - today).days,
            "videos_submitted": videos,
            "speciality": cvs.get(COL_SPECIALITY) or "",
            "hospital": cvs.get(COL_HOSPITAL) or "",
            "interview_type": cvs.get(COL_INTERVIEW_TYPE) or "",
        })
    out.sort(key=lambda s: s["interview_date"])
    return out


# ---------- Calendly: count private calls per email ---------------------------

async def _fetch_private_call_counts(emails: list[str]) -> dict[str, int]:
    """Count Calendly events from forever-ago to now whose event-type name
    matches one of PRIVATE_CALL_NAMES, grouped by invitee email."""
    if not emails:
        return {}
    out: dict[str, int] = {e: 0 for e in emails}

    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        try:
            me = await c.get(f"{CALENDLY_BASE}/users/me", headers=_calendly_headers())
            org = me.json().get("resource", {}).get("current_organization")
        except Exception:
            return out
        if not org:
            return out

        # Pull recent (past 365d) AYCI private-call events grouped by invitee email.
        # Per-email Calendly query is the reliable way (org-wide listing doesn't
        # include invitee details inline).
        max_start = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        min_start = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat().replace("+00:00", "Z")

        # Concurrency-bounded per-email lookup.
        sem = asyncio.Semaphore(6)

        async def _per_email(em: str) -> tuple[str, int]:
            async with sem:
                count = 0
                pt: Optional[str] = None
                while True:
                    p: dict = {
                        "organization": org,
                        "invitee_email": em,
                        "min_start_time": min_start,
                        "max_start_time": max_start,
                        "count": 100,
                        "status": "active",
                    }
                    if pt:
                        p["page_token"] = pt
                    try:
                        rr = await c.get(f"{CALENDLY_BASE}/scheduled_events", headers=_calendly_headers(), params=p)
                    except Exception:
                        break
                    if rr.status_code != 200:
                        break
                    bb = rr.json()
                    for ev in bb.get("collection", []):
                        nm = (ev.get("name") or "").lower()
                        if any(t.lower() in nm for t in PRIVATE_CALL_NAMES):
                            count += 1
                    pt = (bb.get("pagination") or {}).get("next_page_token")
                    if not pt:
                        break
                return em, count

        results = await asyncio.gather(*(_per_email(em) for em in emails if em))
        out.update(dict(results))
    return out


# ---------- Top-level entry ---------------------------------------------------

async def fetch_private_tier_utilisation(days: int = 14) -> dict:
    students = await _fetch_private_tier_with_interviews(days)
    emails = [s["email"] for s in students if s.get("email")]
    call_counts = await _fetch_private_call_counts(emails)

    on_track: list[dict] = []
    flagged: list[dict] = []

    for s in students:
        tier = s["tier"]
        allow = ALLOWANCES[tier]
        thresh = THRESHOLDS[tier]
        videos = s["videos_submitted"]
        calls = call_counts.get(s["email"], 0)
        videos_pct = round((videos / allow["videos"]) * 100) if allow["videos"] else 0
        calls_pct = round((calls / allow["calls"]) * 100) if allow["calls"] else 0
        # math.ceil so that e.g. 50% of 15 = 8 (not int()'s truncated 7).
        videos_min = math.ceil(allow["videos"] * thresh["min_videos_pct"])
        calls_min = thresh["min_calls"]
        passes_videos = videos >= videos_min
        passes_calls = calls >= calls_min
        if thresh["logic"] == "and":
            ok = passes_videos and passes_calls
        else:
            ok = passes_videos or passes_calls

        # Reasons only populated when row is flagged — on_track rows
        # always have an empty list.
        reasons: list[str] = []
        if not ok:
            if not passes_videos:
                reasons.append(f"{videos} / {allow['videos']} videos used (need {videos_min})")
            if not passes_calls:
                reasons.append(f"{calls} / {allow['calls']} calls used (need {calls_min})")

        row = {
            **s,
            "calls_used": calls,
            "calls_allowance": allow["calls"],
            "calls_pct": calls_pct,
            "videos_allowance": allow["videos"],
            "videos_pct": videos_pct,
            "videos_min": videos_min,
            "calls_min": calls_min,
            "logic": thresh["logic"],
            "reasons": reasons,
        }
        (on_track if ok else flagged).append(row)

    # Sort flagged by days-until (most-urgent first)
    flagged.sort(key=lambda r: r["days_until"])
    on_track.sort(key=lambda r: r["days_until"])

    summary_by_tier: dict[str, dict] = {}
    for tier in ("Private Plus", "VIP"):
        ts = [s for s in students if s["tier"] == tier]
        f = [s for s in flagged if s["tier"] == tier]
        ot = [s for s in on_track if s["tier"] == tier]
        summary_by_tier[tier] = {
            "total": len(ts),
            "on_track": len(ot),
            "flagged": len(f),
        }

    return {
        "window_days": days,
        "summary_by_tier": summary_by_tier,
        "flagged": flagged,
        "on_track": on_track,
        "last_refreshed": datetime.now(timezone.utc).isoformat(),
    }
