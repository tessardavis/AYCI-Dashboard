"""
Upcoming Interviews — Monday.com Academy Members board lookup.

Returns students whose Interview Date falls inside [today, today + days].
Academy vs non-Academy students are returned separately because the UI
shows different fields/detail per group.

Non-Academy ("private" in the UI) includes: Academy Private Plus, Academy 1:1,
Upgrade Private Plus, Silver, Gold, Platinum, VIP, Boost & Go, Boost & Go Plus, etc.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone, timedelta, date
from typing import Any

import httpx

from connectors import MONDAY_URL, _monday_headers, TIMEOUT, CALENDLY_BASE, _calendly_headers

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

        # Normalise Monday's free-form Tier dropdown into the canonical group
        # used by Private Tier Utilisation and the Cohort Dashboard, so the
        # same student doesn't read "Silver" in one place and "Private Plus"
        # in another. PRIVATE_PLUS_LABELS / VIP_LABELS are the source of truth
        # in `private_tier_utilisation.py`; we mirror them here. Silver/Gold
        # are legacy product names and now behave as plain Academy.
        _PP_LABELS = {"academy private plus", "upgrade private plus"}
        _VIP_LABELS = {"vip", "platinum"}
        _t_low = tier.strip().lower()
        if _t_low in _PP_LABELS:
            tier_group = "Private Plus"
        elif _t_low in _VIP_LABELS:
            tier_group = "VIP"
        else:
            tier_group = tier  # Academy 1:1, Boost & Go, etc. — keep as-is

        base = {
            "id": it.get("id"),
            "name": it.get("name"),
            "email": email,
            "tier": tier,
            "tier_group": tier_group,
            "interview_date": interview_date,
            "speciality": _txt(COL_SPECIALITY),
            "hospital": _txt(COL_HOSPITAL),
            "monday_url": it.get("url"),
        }

        # Is this an Academy-only student? Tier dropdown can list multiple values
        # (e.g. "Academy, Boost & Go Plus") — if ANYTHING other than plain "Academy"
        # is listed, route them to private.
        # An empty Tier dropdown is treated as plain Academy (team's default — many
        # Academy students never have the dropdown explicitly set).
        # Silver/Gold are legacy product names; students on those tiers today
        # are effectively Academy and should stay in the Academy pane.
        _ACADEMY_EQUIV = {"academy", "silver", "gold"}
        tier_parts = [t.strip().lower() for t in tier.split(",") if t.strip()]
        is_pure_academy = (not tier_parts) or all(tp in _ACADEMY_EQUIV for tp in tier_parts)

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

    # Enrich with Calendly past coaches (who has the student spoken to before?)
    if db is not None:
        try:
            all_emails = [s["email"] for s in academy + private if s.get("email")]
            past_by_email = await fetch_past_coaches_bulk(db, all_emails)
            for s in academy + private:
                em = (s.get("email") or "").lower().strip()
                # Merge two sources:
                #   1) Calendly past events (accurate `last_at`, only completed)
                #   2) Monday "Booked - <name>" tags (authoritative for what's
                #      been agreed, includes future-scheduled calls)
                cal = past_by_email.get(em, []) or []
                mon = _coaches_from_monday_items(s)
                s["past_coaches"] = _merge_coach_lists(cal, mon)
        except Exception:
            for s in academy + private:
                s.setdefault("past_coaches", _coaches_from_monday_items(s))

    return {
        "window": {"start": start_str, "end": end_str, "days": days},
        "academy": academy,
        "private": private,
    }


def _coaches_from_monday_items(student: dict) -> list[dict]:
    """Parse 'Booked - <name>' (or 'Used - <name>') labels out of the call /
    mock / bonus column items, return [{name, count, last_at: None}, ...].
    Calendly tells us *when*; Monday tells us *which*. Combining both gives
    the full picture so a student who's booked 4 calls but only had 1 yet
    isn't shown as 'spoke with 1 coach'."""
    import re
    out: dict[str, dict] = {}
    sections = [
        (student.get("calls_30min") or {}).get("items") or [],
        (student.get("mock_interviews") or {}).get("items") or [],
        (student.get("bonus_calls") or {}).get("items") or [],
    ]
    for items in sections:
        for it in items:
            txt = (it.get("text") or "").strip()
            if not txt:
                continue
            # Match "Booked - Tessa", "Used - Anoop", "Booked: Becky Platt"
            m = re.match(r"^(?:booked|used|completed|done)\s*[-:]\s*(.+)$", txt, re.I)
            if not m:
                continue
            name = m.group(1).strip()
            # Drop trailing parens / dates if present
            name = re.split(r"\s[\(\d]", name)[0].strip()
            if not name:
                continue
            key = name.lower()
            entry = out.get(key)
            if entry is None:
                out[key] = {"name": name, "count": 1, "last_at": None}
            else:
                entry["count"] += 1
    return list(out.values())


def _merge_coach_lists(calendly: list[dict], monday: list[dict]) -> list[dict]:
    """Merge two coach lists by lowercased first-token. Monday tells us a
    coach is involved; Calendly tells us actual call dates. Whichever has
    the higher count wins (so we don't double-count when both sources see
    the same call). `last_at` always comes from Calendly when available."""
    def _key(name: str) -> str:
        return (name or "").strip().split()[0].lower() if name else ""

    merged: dict[str, dict] = {}
    for c in (calendly or []) + (monday or []):
        k = _key(c.get("name"))
        if not k:
            continue
        e = merged.get(k)
        if e is None:
            merged[k] = dict(c)
        else:
            e["count"] = max(int(e.get("count") or 0), int(c.get("count") or 0))
            # Prefer the longer / more-canonical name (usually Calendly's
            # full name vs Monday's first-name only)
            if len((c.get("name") or "")) > len(e.get("name") or ""):
                e["name"] = c["name"]
            if c.get("last_at") and (not e.get("last_at") or c["last_at"] > e["last_at"]):
                e["last_at"] = c["last_at"]
    return sorted(merged.values(), key=lambda x: (-(x.get("count") or 0), x.get("last_at") or ""), reverse=False)


# ---- Calendly past-coaches enrichment -------------------------------------
# Per-email, 24h-cached lookup of which coaches the student has had calls with.
PAST_COACHES_TTL_HOURS = 24
PAST_COACHES_LOOKBACK_DAYS = 365
PAST_COACHES_CONCURRENCY = 6


async def _fetch_past_coaches_one(client: httpx.AsyncClient, org: str, email: str) -> list[dict]:
    """Calendly: list this invitee's past *active* events, group by host."""
    target = email.strip().lower()
    if not target:
        return []
    min_start = (datetime.now(timezone.utc) - timedelta(days=PAST_COACHES_LOOKBACK_DAYS)).isoformat().replace("+00:00", "Z")
    max_start = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    by_host: dict[str, dict] = {}
    page_token: str | None = None
    pages = 0
    while pages < 4:  # cap at 200 events per student — plenty
        q: dict[str, Any] = {
            "organization": org,
            "invitee_email": target,
            "count": 50,
            "sort": "start_time:desc",
            "status": "active",
            "min_start_time": min_start,
            "max_start_time": max_start,
        }
        if page_token:
            q["page_token"] = page_token
        try:
            r = await client.get(f"{CALENDLY_BASE}/scheduled_events", headers=_calendly_headers(), params=q)
        except Exception:
            break
        if r.status_code != 200:
            break
        body = r.json()
        for ev in body.get("collection", []):
            membs = ev.get("event_memberships") or []
            if not membs:
                continue
            host = membs[0].get("user_name") or membs[0].get("user_email") or "Unknown"
            start = ev.get("start_time") or ""
            entry = by_host.get(host)
            if entry is None:
                by_host[host] = {"name": host, "count": 1, "last_at": start, "dates": [start] if start else []}
            else:
                entry["count"] += 1
                if start:
                    entry.setdefault("dates", []).append(start)
                    if start > (entry.get("last_at") or ""):
                        entry["last_at"] = start
        page_token = (body.get("pagination") or {}).get("next_page_token")
        pages += 1
        if not page_token:
            break
    return sorted(by_host.values(), key=lambda x: x.get("last_at") or "", reverse=True)


async def fetch_past_coaches_bulk(db, emails: list[str]) -> dict[str, list[dict]]:
    """
    Returns {email_lower: [{name, count, last_at}]} for each email.
    Cached per-email in `cache` collection for 24 h. Missing entries are
    fetched concurrently with bounded concurrency to stay polite to Calendly.
    """
    if not emails:
        return {}
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=PAST_COACHES_TTL_HOURS)).isoformat()
    out: dict[str, list[dict]] = {}
    needed: list[str] = []
    seen: set[str] = set()
    for raw in emails:
        em = (raw or "").strip().lower()
        if not em or em in seen:
            continue
        seen.add(em)
        doc = await db.cache.find_one({"key": f"calendly_past_hosts:{em}"})
        if doc and doc.get("computed_at", "") >= cutoff and isinstance(doc.get("value"), list):
            out[em] = doc["value"]
        else:
            needed.append(em)
    if not needed:
        return out

    if not os.environ.get("CALENDLY_TOKEN"):
        return out

    sem = asyncio.Semaphore(PAST_COACHES_CONCURRENCY)
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        try:
            me = await c.get(f"{CALENDLY_BASE}/users/me", headers=_calendly_headers())
            me.raise_for_status()
            org = me.json().get("resource", {}).get("current_organization")
        except Exception:
            return out
        if not org:
            return out

        async def run(em: str) -> tuple[str, list[dict]]:
            async with sem:
                try:
                    hosts = await _fetch_past_coaches_one(c, org, em)
                except Exception:
                    hosts = []
                return em, hosts

        results = await asyncio.gather(*(run(em) for em in needed))

    now_iso = now.isoformat()
    for em, hosts in results:
        out[em] = hosts
        await db.cache.update_one(
            {"key": f"calendly_past_hosts:{em}"},
            {"$set": {
                "key": f"calendly_past_hosts:{em}",
                "value": hosts,
                "computed_at": now_iso,
            }},
            upsert=True,
        )
    return out
