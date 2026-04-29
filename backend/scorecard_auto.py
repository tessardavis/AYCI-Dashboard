"""
Auto-computed Weekly Scorecard metrics.

For each metric we know how to derive, a function takes (db, week_start_date,
week_end_date) and returns either a numeric value or None if it can't be
computed for that window. Mapped onto metric NAMES (case-insensitive) so the
endpoint `/api/scorecard/auto-compute` can fan out across all of them.

Caching: per week + metric in `fn_cache` for 1 h.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone, date
from typing import Any, Optional

import httpx

from connectors import (
    CIRCLE_BASE,
    _circle_headers,
    CALENDLY_BASE,
    _calendly_headers,
    MONDAY_URL,
    _monday_headers,
    TIMEOUT,
)


# Tier strings on Monday's Academy Members board that count as "private tier"
PRIVATE_TIER_LABELS = {
    "Academy Private Plus",
    "Academy 1:1",
    "Upgrade Private Plus",
    "Silver",
    "Gold",
    "Platinum",
    "VIP",
    "Boost & Go",
    "Boost & Go Plus",
}

# Constants from elsewhere in the codebase
ACADEMY_MEMBERS_BOARD_ID = 1956295952
COL_TIER = "color_mkpkrnz0"
COL_INTERVIEW_DATE = "date_mkr7rdv7"
COL_EMAIL = "email_mkqxv0j0"

# Coach Calendly hosts whose names contain these substrings count as "coach"
# calls for the "Hours of Private Tier Calls" metric.
COACH_NAMES_LC = [
    "tessa davis", "becky platt", "anoop", "kat priddis",
    "charlotte wyeth", "anne beh", "zinnirah",
]

# Circle space IDs
SHARE_YOUR_WINS_SPACE_ID = 996901


def _week_iso(d: date) -> tuple[str, str]:
    """Return (start_iso_utc, end_iso_utc) for the calendar week starting on
    Mon `d` and ending Sun 23:59:59."""
    start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=7) - timedelta(seconds=1)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


# ---------- Number of Interviews ----------------------------------------------
async def compute_number_of_interviews(db, week_start: date, week_end: date) -> dict:
    """Count students on Monday's Academy Members board whose Interview Date
    falls inside [week_start, week_end]. Includes Academy + private tiers."""
    start_str = week_start.isoformat()
    end_str = week_end.isoformat()
    q = """
    query ($boardId: ID!, $cursor: String) {
      boards(ids: [$boardId]) {
        items_page(limit: 200, cursor: $cursor) {
          cursor
          items {
            id name
            column_values(ids: ["%s"]) {
              id text
            }
          }
        }
      }
    }
    """ % COL_INTERVIEW_DATE

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

    count = 0
    for it in items:
        cvs = {cv.get("id"): (cv.get("text") or "").strip() for cv in (it.get("column_values") or [])}
        d = cvs.get(COL_INTERVIEW_DATE) or ""
        if not d:
            continue
        # Date format on Monday is "YYYY-MM-DD" or "YYYY-MM-DD HH:MM"
        try:
            ds = d.split(" ")[0]
            di = datetime.fromisoformat(ds).date()
        except ValueError:
            continue
        if start_str <= di.isoformat() <= end_str:
            count += 1

    return {"value": count, "denominator": len(items), "explain": f"{count} Academy Members with Interview Date inside week"}


# ---------- Hours of Private Tier Calls ---------------------------------------
async def compute_hours_private_calls(db, week_start: date, week_end: date) -> dict:
    """Sum Calendly event durations during the week where the host is one of
    our coaches. We assume the invitee is a private-tier student because
    Private Plus / VIP / Boost are the only paying tiers using Calendly with
    AYCI coaches."""
    start_iso, end_iso = _week_iso(week_start)
    total_seconds = 0
    event_count = 0
    by_coach: dict[str, int] = {}

    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        # Get current user / org
        try:
            me = await c.get(f"{CALENDLY_BASE}/users/me", headers=_calendly_headers())
            org = me.json().get("resource", {}).get("current_organization")
        except Exception:
            return {"value": None, "explain": "Couldn't reach Calendly /users/me"}

        page_token: Optional[str] = None
        while True:
            params: dict[str, Any] = {
                "organization": org,
                "min_start_time": start_iso,
                "max_start_time": end_iso,
                "count": 100,
                "status": "active",
            }
            if page_token:
                params["page_token"] = page_token
            r = await c.get(f"{CALENDLY_BASE}/scheduled_events", headers=_calendly_headers(), params=params)
            if r.status_code != 200:
                break
            body = r.json()
            for ev in body.get("collection", []):
                membs = ev.get("event_memberships") or []
                if not membs:
                    continue
                host = (membs[0].get("user_name") or "").lower()
                if not any(c_name in host for c_name in COACH_NAMES_LC):
                    continue
                # Skip the weekly "testimonial" type — counted separately
                evt = (ev.get("name") or "").lower()
                if "testimonial" in evt:
                    continue
                try:
                    s = datetime.fromisoformat(ev["start_time"].replace("Z", "+00:00"))
                    e = datetime.fromisoformat(ev["end_time"].replace("Z", "+00:00"))
                    secs = int((e - s).total_seconds())
                except (KeyError, ValueError):
                    continue
                total_seconds += secs
                event_count += 1
                by_coach[membs[0].get("user_name") or "Unknown"] = by_coach.get(membs[0].get("user_name") or "Unknown", 0) + secs
            page_token = (body.get("pagination") or {}).get("next_page_token")
            if not page_token:
                break

    hours = round(total_seconds / 3600, 1)
    explain = f"{event_count} coach events, total {hours}h"
    return {"value": hours, "explain": explain, "by_coach_seconds": by_coach}


# ---------- Testimonial Calls Recorded ---------------------------------------
async def compute_testimonial_calls(db, week_start: date, week_end: date) -> dict:
    """Count Calendly events whose name contains 'testimonial' that occurred
    in the week."""
    start_iso, end_iso = _week_iso(week_start)
    count = 0
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        try:
            me = await c.get(f"{CALENDLY_BASE}/users/me", headers=_calendly_headers())
            org = me.json().get("resource", {}).get("current_organization")
        except Exception:
            return {"value": None, "explain": "Couldn't reach Calendly /users/me"}

        page_token: Optional[str] = None
        while True:
            params: dict[str, Any] = {
                "organization": org,
                "min_start_time": start_iso,
                "max_start_time": end_iso,
                "count": 100,
                "status": "active",
            }
            if page_token:
                params["page_token"] = page_token
            r = await c.get(f"{CALENDLY_BASE}/scheduled_events", headers=_calendly_headers(), params=params)
            if r.status_code != 200:
                break
            body = r.json()
            for ev in body.get("collection", []):
                if "testimonial" in (ev.get("name") or "").lower():
                    count += 1
            page_token = (body.get("pagination") or {}).get("next_page_token")
            if not page_token:
                break
    return {"value": count, "explain": f"{count} Calendly events with 'testimonial' in name"}


# ---------- Wins Shared --------------------------------------------------------
async def compute_wins_shared(db, week_start: date, week_end: date) -> dict:
    """Count posts in the 'Share Your Wins' Circle space during the week
    (numerator). Denominator = number of interviews completed this week. Returns
    a percentage. If denominator is zero we fall back to the raw count."""
    start_iso = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc).isoformat()
    end_iso = (datetime(week_end.year, week_end.month, week_end.day, tzinfo=timezone.utc) + timedelta(days=1)).isoformat()
    posts_in_week = 0
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        page = 1
        while page <= 20:
            r = await c.get(
                f"{CIRCLE_BASE}/posts",
                headers=_circle_headers(),
                params={"space_id": SHARE_YOUR_WINS_SPACE_ID, "per_page": 100, "page": page},
            )
            if r.status_code != 200:
                break
            recs = r.json().get("records") or []
            if not recs:
                break
            for p in recs:
                ca = p.get("created_at") or ""
                if start_iso <= ca < end_iso:
                    posts_in_week += 1
            # Stop when we drop below the start window
            oldest = (recs[-1].get("created_at") or "")
            if oldest and oldest < start_iso:
                break
            if len(recs) < 100:
                break
            page += 1

    # Denominator = "Number of Interviews" for this week
    interviews = await compute_number_of_interviews(db, week_start, week_end)
    denom = (interviews.get("value") or 0)
    if denom > 0:
        pct = round((posts_in_week / denom) * 100, 1)
        return {
            "value": pct,
            "explain": f"{posts_in_week} wins shared / {denom} interviews this week",
            "numerator": posts_in_week,
            "denominator": denom,
        }
    return {
        "value": posts_in_week,
        "explain": f"{posts_in_week} wins shared (no interviews this week to divide by)",
        "numerator": posts_in_week,
        "denominator": 0,
    }


# ---------- Results Received ---------------------------------------------------
TALLY_INTERVIEW_DATE_FORM_ID = "nGyGj2"


async def compute_results_received(db, week_start: date, week_end: date) -> dict:
    """Count Tally submissions during the week where the student told us
    how their interview went (the result question's answer matches one of
    the result option strings). As a % of interviews-this-week.
    """
    import os
    submitted_with_result = 0
    start_iso = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc)
    end_iso = start_iso + timedelta(days=7)

    # Strings that indicate an actual outcome was reported
    RESULT_ANSWERS = [
        "i got it",
        "unfortunately i didn't get it",
        "unfortunately i didn",
        "my interview was rescheduled",
        "interview was rescheduled",
    ]

    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        page = 1
        bail = False
        while page <= 30 and not bail:
            r = await c.get(
                f"https://api.tally.so/forms/{TALLY_INTERVIEW_DATE_FORM_ID}/submissions",
                headers={"Authorization": f"Bearer {os.environ['TALLY_API_KEY']}"},
                params={"page": page, "limit": 100},
            )
            if r.status_code != 200:
                break
            body = r.json()
            subs = body.get("submissions", [])
            if not subs:
                break
            for s in subs:
                ca = s.get("submittedAt") or s.get("createdAt") or ""
                try:
                    dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if dt < start_iso:
                    bail = True
                    break
                if dt >= end_iso:
                    continue
                # Scan all answer strings for any of the RESULT_ANSWERS
                answers_blob = " ".join(
                    str((resp.get("answer") or "")).lower()
                    for resp in (s.get("responses") or [])
                )
                if any(a in answers_blob for a in RESULT_ANSWERS):
                    submitted_with_result += 1
            page += 1
            if not body.get("hasMore", False) and len(subs) < 100:
                break

    interviews = await compute_number_of_interviews(db, week_start, week_end)
    denom = (interviews.get("value") or 0)
    if denom > 0:
        pct = round((submitted_with_result / denom) * 100, 1)
        return {
            "value": pct,
            "explain": f"{submitted_with_result} interview-result submissions / {denom} interviews this week",
            "numerator": submitted_with_result,
            "denominator": denom,
        }
    return {
        "value": submitted_with_result,
        "explain": f"{submitted_with_result} interview-result submissions (no interviews this week to divide by)",
        "numerator": submitted_with_result,
        "denominator": 0,
    }


# ---------- Active Academy Members --------------------------------------------
# Circle tags applied via gamification — coach maintains these manually on
# each member. Match-on-presence (any of these tags = active for that
# milestone). Uses the active cohort tag (set per launch) to find members.

INTRO_POST_TAG_NAMES = ["verified!", "verified community member", "intro post", "introduction", "intro"]
MILESTONE_TAG_NAMES = [
    # Coach-applied tags that signal milestone completion (5 cohort milestones).
    # The exact tag names shown to coaches in Circle are based on the
    # programme content. These are the closest matches we've seen on
    # APR-26 cohort members so far. Update as new milestones are added.
    "uso", "usos",
    "examples",
    "senior level thinking", "senior-level thinking", "senior thinking",
    "job specific", "job-specific knowledge",
    "bringing in you", "bring in you",
    "daily prep",
    "baseline tmay",
    "deep dive",
    "video course legend",
    "boss",
    "interview week",
    "rfi-",
]

ACTIVE_MEMBER_DEFAULT_COHORT_TAG = "Apr '26"


async def _circle_member_tags_for_cohort(client: httpx.AsyncClient, cohort_tag: str) -> list[dict]:
    """List Circle community members tagged with the cohort. Returns the
    raw member dicts (each may include a `tags` list)."""
    members: list[dict] = []
    page = 1
    while page <= 50:
        r = await client.get(
            f"{CIRCLE_BASE}/community_members",
            headers=_circle_headers(),
            params={"per_page": 100, "page": page},
        )
        if r.status_code != 200:
            break
        recs = r.json().get("records") or []
        if not recs:
            break
        members.extend(recs)
        if len(recs) < 100:
            break
        page += 1
    return members


async def compute_active_members(db, week_start: date, week_end: date) -> dict:
    """% of the current cohort's members who have an Intro Post tag OR at
    least one of the 5 milestone tags. Cohort tag taken from the most recent
    launch.code (e.g. APR-26 → 'Apr '26').
    """
    # Best-effort: fetch the most recent launch code from the launches table
    cohort_tag = ACTIVE_MEMBER_DEFAULT_COHORT_TAG
    try:
        launch = await db.launches.find_one(
            {}, {"_id": 0, "code": 1}, sort=[("start_date", -1)]
        )
        code = (launch or {}).get("code") or ""
        # APR-26 -> "Apr '26"
        if "-" in code:
            mon, yy = code.split("-")
            from coach_activity import MONTH_NAMES
            mon_name = (MONTH_NAMES.get(mon.upper(), (mon,))[0] if MONTH_NAMES else mon)
            cohort_tag = f"{mon_name} '{yy}"
    except Exception:
        pass

    # Cohort tag includes a rosette/emoji prefix in Circle (e.g. "🏵️ Apr '26")
    # so we strip non-alphanumerics and compare on the month-year stem only.
    cohort_tag_lc = cohort_tag.lower()
    intros_lc = [s.lower() for s in INTRO_POST_TAG_NAMES]
    miles_lc = [s.lower() for s in MILESTONE_TAG_NAMES]

    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        members = await _circle_member_tags_for_cohort(c, cohort_tag)

    cohort_members = []
    for m in members:
        tag_objects = m.get("member_tags") or m.get("tags") or []
        tags = [(t.get("name") or "").lower() for t in tag_objects]
        # Match on substring — handles "🏵️ Apr '26" and any other emoji prefix
        if any(cohort_tag_lc in t for t in tags):
            cohort_members.append({"name": m.get("name"), "tags": tags})

    if not cohort_members:
        return {"value": 0, "explain": f"No members tagged with {cohort_tag!r}"}

    active = 0
    for m in cohort_members:
        tags = m["tags"]
        intro = any(any(i in t for i in intros_lc) for t in tags)
        milestone = any(any(ms in t for ms in miles_lc) for t in tags)
        if intro or milestone:
            active += 1

    pct = round((active / len(cohort_members)) * 100, 1)
    return {
        "value": pct,
        "explain": f"{active}/{len(cohort_members)} members in {cohort_tag} have intro post or ≥1 milestone",
        "numerator": active,
        "denominator": len(cohort_members),
        "cohort_tag": cohort_tag,
    }


# ---------- Public dispatcher --------------------------------------------------
# Map metric NAME (lowercase) → compute fn.
COMPUTE_MAP: dict[str, Any] = {
    "interviews this week": compute_number_of_interviews,
    "hours of private tier calls": compute_hours_private_calls,
    "testimonial calls recorded": compute_testimonial_calls,
    "wins shared": compute_wins_shared,
    "results received": compute_results_received,
    "active academy members": compute_active_members,
}


async def auto_compute_all(db, week_start: date) -> dict:
    """For one week-start date, fan out the 6 supported metrics in parallel."""
    week_end = week_start + timedelta(days=6)
    keys = list(COMPUTE_MAP.keys())
    results = await asyncio.gather(
        *(COMPUTE_MAP[k](db, week_start, week_end) for k in keys),
        return_exceptions=True,
    )
    out: dict[str, dict] = {}
    for k, r in zip(keys, results):
        if isinstance(r, Exception):
            out[k] = {"value": None, "error": str(r)}
        else:
            out[k] = r
    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "metrics": out,
    }
