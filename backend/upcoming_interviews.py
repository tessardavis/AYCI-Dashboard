"""
Upcoming Interviews — Monday.com Academy Members board lookup.

Returns students whose Interview Date falls inside [today, today + days].
Academy vs non-Academy students are returned separately because the UI
shows different fields/detail per group.

Non-Academy ("private" in the UI) includes: Academy Private Plus, Academy 1:1,
Upgrade Private Plus, Silver, Gold, Platinum, VIP, Boost & Go, Boost & Go Plus, etc.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta, date
from typing import Any

import httpx

from connectors import MONDAY_URL, _monday_headers, TIMEOUT

ACADEMY_MEMBERS_BOARD_ID = 1956295952

# Column IDs on the Academy Members board
COL_INTERVIEW_DATE = "date_mkr7rdv7"
COL_TIER = "dropdown_mkqxgqbq"
COL_EMAIL = "email_mkqxv0j0"
COL_SPECIALITY = "dropdown_mkqxk94m"
COL_HOSPITAL = "text_mkrqzraa"
COL_PRIVATE_CHAT_LINK = "text_mky9xzew"
COL_COHORT_JOINED = None  # optional extra — not needed

# Allowance status columns (30-min calls, 60-min mocks, bonus calls, etc.)
# Every column here represents ONE call/mock slot.
CALL_COLS = [
    ("color_mkqxp9nt", "Call 1"),
    ("color_mkqxxemb", "Call 2"),
    ("color_mkqxvfa5", "Call 3"),
    ("color_mkqxveyf", "Call 4"),
]
MOCK_COLS = [
    ("color_mkqxshf3", "Mock Interview 1"),
    ("color_mkqxn5j4", "Mock Interview 2"),
    ("color_mkr0wecr", "Mock interview (cohort before April)"),
]
BONUS_COLS = [
    ("color_mkqx1y49", "Bonus Call"),
    ("color_mkr0mq25", "Gold Call"),
    ("color_mkr0ef7c", "Platinum Call"),
    ("color_mkrwvwe2", "15 minute call"),
    ("color_mkqxkp6d", "Testimonial Call"),
    ("color_mks248ex", "Mini-webinar bonus"),
]

COL_VIDEO_ALLOWANCE = "numeric_mkxfvz1k"
COL_VIDEOS_SUBMITTED = "numeric_mkxfq65c"

ALL_COLUMN_IDS = [
    COL_INTERVIEW_DATE, COL_TIER, COL_EMAIL, COL_SPECIALITY, COL_HOSPITAL,
    COL_PRIVATE_CHAT_LINK, COL_VIDEO_ALLOWANCE, COL_VIDEOS_SUBMITTED,
] + [c for c, _ in CALL_COLS + MOCK_COLS + BONUS_COLS]


def _allowance(cols_by_id: dict[str, dict], specs: list[tuple[str, str]]) -> dict:
    """Summarise a group of status columns as {used, available, total, items}."""
    used = 0
    available = 0
    items = []
    for cid, label in specs:
        col = cols_by_id.get(cid)
        if not col:
            continue
        txt = (col.get("text") or "").strip()
        if not txt:
            # Blank → not eligible for this slot in this tier
            continue
        if txt.lower().startswith("booked") or txt.lower() in ("done", "completed"):
            used += 1
            status = "used"
        elif txt.lower() == "eligible":
            available += 1
            status = "available"
        else:
            # Other non-empty status → treat as "other" (not counted either way)
            status = "other"
        items.append({"label": label, "status": status, "text": txt})
    return {
        "used": used,
        "available": available,
        "total": used + available,
        "items": items,
    }


async def fetch_upcoming_interviews(db=None, days: int = 14) -> dict:
    """
    Returns:
      {
        "window": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "days": N},
        "academy":  [ {simple fields}, ... ],
        "private":  [ {full fields + allowances}, ... ],
      }
    Both lists are sorted by interview_date ascending.
    """
    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=days)
    start_str = today.isoformat()
    end_str = end.isoformat()

    query = """
    query ($boardId: ID!, $dates: CompareValue!, $limit: Int!, $cursor: String) {
      boards(ids: [$boardId]) {
        items_page(
          limit: $limit,
          cursor: $cursor,
          query_params: {
            rules: [
              { column_id: "%s", compare_value: $dates, operator: between }
            ]
          }
        ) {
          cursor
          items {
            id
            name
            url
            column_values { id text column { title } }
          }
        }
      }
    }
    """ % COL_INTERVIEW_DATE

    items: list[dict] = []
    cursor: str | None = None
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        while True:
            r = await c.post(
                MONDAY_URL,
                headers={**_monday_headers(), "Content-Type": "application/json"},
                json={
                    "query": query,
                    "variables": {
                        "boardId": str(ACADEMY_MEMBERS_BOARD_ID),
                        "dates": [start_str, end_str],
                        "limit": 100,
                        "cursor": cursor,
                    },
                },
            )
            r.raise_for_status()
            body = r.json()
            if body.get("errors"):
                raise RuntimeError(f"Monday error: {body['errors']}")
            page = (body.get("data", {}).get("boards") or [{}])[0].get("items_page") or {}
            items.extend(page.get("items") or [])
            cursor = page.get("cursor")
            if not cursor or not (page.get("items") or []):
                break

    academy: list[dict] = []
    private: list[dict] = []

    for it in items:
        cols_by_id: dict[str, dict] = {col["id"]: col for col in (it.get("column_values") or [])}

        def _txt(cid: str) -> str:
            return (cols_by_id.get(cid, {}).get("text") or "").strip()

        tier = _txt(COL_TIER)
        interview_date = _txt(COL_INTERVIEW_DATE)
        email = _txt(COL_EMAIL)
        if not interview_date:
            continue

        base = {
            "id": it.get("id"),
            "name": it.get("name"),
            "email": email,
            "tier": tier,
            "interview_date": interview_date,
            "speciality": _txt(COL_SPECIALITY),
            "hospital": _txt(COL_HOSPITAL),
            "monday_url": it.get("url"),
        }

        # Is this an Academy-only student? Tier dropdown can list multiple values
        # (e.g. "Academy, Boost & Go Plus") — if ANYTHING other than plain "Academy"
        # is listed, route them to private.
        tier_parts = [t.strip().lower() for t in tier.split(",") if t.strip()]
        is_pure_academy = tier_parts == ["academy"]

        if is_pure_academy:
            academy.append(base)
        else:
            calls = _allowance(cols_by_id, CALL_COLS)
            mocks = _allowance(cols_by_id, MOCK_COLS)
            bonus = _allowance(cols_by_id, BONUS_COLS)

            video_allowance_raw = _txt(COL_VIDEO_ALLOWANCE)
            video_used_raw = _txt(COL_VIDEOS_SUBMITTED)
            try:
                video_allowance = int(float(video_allowance_raw)) if video_allowance_raw else 0
            except ValueError:
                video_allowance = 0
            try:
                video_used = int(float(video_used_raw)) if video_used_raw else 0
            except ValueError:
                video_used = 0

            private.append({
                **base,
                "private_chat_link": _txt(COL_PRIVATE_CHAT_LINK),
                "calls_30min": calls,
                "mock_interviews": mocks,
                "bonus_calls": bonus,
                "videos": {
                    "submitted": video_used,
                    "allowance": video_allowance,
                    "remaining": max(0, video_allowance - video_used),
                },
            })

    academy.sort(key=lambda x: x["interview_date"])
    private.sort(key=lambda x: x["interview_date"])

    # Enrich with Tally interview type + history count (best-effort, never blocks)
    if db is not None:
        try:
            from tally_lookup import lookup_emails_bulk
            all_emails = [s["email"] for s in academy + private if s.get("email")]
            tally_by_email = await lookup_emails_bulk(db, all_emails)
            for s in academy + private:
                em = (s.get("email") or "").lower().strip()
                t = tally_by_email.get(em) or {}
                s["interview_type"] = t.get("type")
                s["tally_history_count"] = t.get("history_count", 0)
                s["tally_last_interview"] = (
                    (t.get("history") or [{}])[0] if t.get("history") else None
                )
        except Exception:
            # Tally enrichment is optional — silently skip on error
            pass

    return {
        "window": {"start": start_str, "end": end_str, "days": days},
        "academy": academy,
        "private": private,
    }
