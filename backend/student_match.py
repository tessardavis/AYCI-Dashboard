"""
Cross-source student matcher for Support Tickets.

Given any combination of (email, phone, name), find the student's Monday
record and return a slim context object for display on the ticket:
  {matched, email, name, tier, cohort, monday_item_id, monday_url}

Used by the ticket detail panel so every ticket — regardless of whether it
came in via email, Tally form, manual entry, or WhatsApp — can deep-link to
the Student Lookup page and show the team quick context.

Match is cached on the ticket under `student_match` and `student_match_at`
so we don't re-query Monday on every ticket view. Cache expires after
STUDENT_MATCH_TTL_HOURS or when the admin forces a refresh.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from connectors import MONDAY_URL, _monday_headers, TIMEOUT

logger = logging.getLogger(__name__)

ACADEMY_MEMBERS_BOARD_ID = 1956295952

COL_EMAIL = "email_mkqxv0j0"
COL_PHONE = "phone_mkqxcapx"
COL_TIER = "dropdown_mkqxgqbq"
COL_COHORT_JOINED = "dropdown_mkqxhw8p"

STUDENT_MATCH_TTL_HOURS = 24


def _normalise_phone(raw: str) -> str:
    """Strip to digits only. E.g. '+44 7700 900999' → '447700900999'."""
    if not raw:
        return ""
    return re.sub(r"\D", "", str(raw))


def _txt(cols: list[dict], col_id: str) -> str:
    for c in cols or []:
        if c.get("id") == col_id:
            return (c.get("text") or "").strip()
    return ""


async def _monday_search_by_email(email: str) -> Optional[dict]:
    """Find an Academy Members row whose Email column matches."""
    q = """
    query ($boardId: ID!, $val: CompareValue!, $limit: Int!) {
      boards(ids: [$boardId]) {
        items_page(
          limit: $limit,
          query_params: { rules: [{ column_id: "%s", compare_value: $val, operator: contains_text }] }
        ) {
          items { id name url column_values { id text } }
        }
      }
    }
    """ % COL_EMAIL
    vars_ = {"boardId": str(ACADEMY_MEMBERS_BOARD_ID), "val": email.lower(), "limit": 5}
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(
            MONDAY_URL,
            headers={**_monday_headers(), "Content-Type": "application/json"},
            json={"query": q, "variables": vars_},
        )
        r.raise_for_status()
        body = r.json()
    items = (
        (body.get("data") or {}).get("boards", [{}])[0].get("items_page", {}).get("items") or []
    )
    target = email.lower().strip()
    for it in items:
        if _txt(it.get("column_values") or [], COL_EMAIL).lower() == target:
            return it
    return items[0] if items else None


async def _monday_search_by_phone(phone_digits: str) -> Optional[dict]:
    """Find an Academy Members row whose Phone column matches digit-normalised."""
    if not phone_digits:
        return None
    # We can't filter Monday's phone column server-side (column-type rules are
    # fiddly for phone) — pull a page and scan client-side. The Phone column's
    # `text` representation contains the number as the user typed it, so we
    # normalise both sides to digits.
    q = """
    query ($boardId: ID!, $limit: Int!, $cursor: String) {
      boards(ids: [$boardId]) {
        items_page(limit: $limit, cursor: $cursor) {
          cursor
          items { id name url column_values { id text } }
        }
      }
    }
    """
    cursor: Optional[str] = None
    # Try the last-N (most recently updated) items first — the team rarely
    # messages ancient alumni via WhatsApp — but cap at 1000 items total
    # (~10 pages) so we don't scan the whole 5000-item board on every ticket.
    scanned = 0
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        while scanned < 1000:
            vars_: dict = {"boardId": str(ACADEMY_MEMBERS_BOARD_ID), "limit": 100}
            if cursor:
                vars_["cursor"] = cursor
            r = await c.post(
                MONDAY_URL,
                headers={**_monday_headers(), "Content-Type": "application/json"},
                json={"query": q, "variables": vars_},
            )
            r.raise_for_status()
            body = r.json()
            page = (
                (body.get("data") or {}).get("boards", [{}])[0].get("items_page") or {}
            )
            items = page.get("items") or []
            for it in items:
                txt_phone = _txt(it.get("column_values") or [], COL_PHONE)
                if not txt_phone:
                    continue
                digits = _normalise_phone(txt_phone)
                # Match by last 10 digits to handle country-code omission
                if digits and (
                    digits == phone_digits
                    or digits[-10:] == phone_digits[-10:]
                ):
                    return it
            cursor = page.get("cursor")
            scanned += len(items)
            if not cursor or not items:
                break
    return None


def _build_match(item: dict) -> dict:
    cols = item.get("column_values") or []
    return {
        "matched": True,
        "name": (item.get("name") or "").strip(),
        "email": _txt(cols, COL_EMAIL).lower() or None,
        "phone": _txt(cols, COL_PHONE) or None,
        "tier": _txt(cols, COL_TIER) or None,
        "cohort": _txt(cols, COL_COHORT_JOINED) or None,
        "monday_item_id": item.get("id"),
        "monday_url": item.get("url"),
    }


async def _resolve_email_by_name(db, name: str) -> Optional[str]:
    """Circle DM tickets land with only a student name (no email/phone). Use the
    cached Circle members list to map name → email. Returns the email of the
    top match only when it's a strong (>=80) hit, to avoid linking the wrong
    student on weak fuzzy matches."""
    if not name or len(name.strip()) < 2:
        return None
    try:
        import student_lookup as lookup
        hits = await lookup.name_search(db, name, limit=3)
    except Exception as e:
        logger.warning(f"[student-match] name_search failed: {e}")
        return None
    if not hits:
        return None
    top = hits[0]
    if (top.get("match_score") or 0) >= 80 and top.get("email"):
        return top["email"].strip().lower()
    return None


async def match_student(
    *,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    name: Optional[str] = None,
    db=None,
) -> dict:
    """Try email first (cheap indexed search), then phone (board scan), then
    name (Circle cache → email → Monday). Returns a student-match dict —
    `matched=False` when no row found."""
    try:
        if email:
            item = await _monday_search_by_email(email.strip().lower())
            if item:
                return _build_match(item)
        if phone:
            digits = _normalise_phone(phone)
            if digits:
                item = await _monday_search_by_phone(digits)
                if item:
                    return _build_match(item)
        if name and db is not None:
            resolved = await _resolve_email_by_name(db, name)
            if resolved:
                item = await _monday_search_by_email(resolved)
                if item:
                    out = _build_match(item)
                    out["matched_via"] = "name"
                    return out
    except Exception as e:
        logger.warning(f"[student-match] lookup failed: {e}")
        return {"matched": False, "error": str(e)}
    return {"matched": False}


async def ensure_ticket_student_match(db, ticket: dict, *, force: bool = False) -> dict:
    """Populate `ticket.student_match` from Monday if missing/stale. Returns the
    match dict. Mutates the ticket doc in place."""
    cache = ticket.get("student_match")
    cached_at = ticket.get("student_match_at")
    cached_matched = bool(cache and cache.get("matched"))
    # Re-try unmatched tickets on every open (cheap — Circle name cache is in
    # Mongo, Monday email search is ~500ms). Without this, Circle DM tickets
    # that landed before the name-fallback existed would stay un-linked for
    # 24h. Only the cache for successful matches is honoured long-term.
    if cache and cached_at and not force and cached_matched:
        ts = cached_at
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(hours=STUDENT_MATCH_TTL_HOURS)
            if ts > cutoff:
                return cache

    email = (ticket.get("student_email") or "").strip().lower()
    phone = (
        ticket.get("wati_wa_id")
        or ticket.get("student_phone")
        or ""
    )
    name = (ticket.get("student_name") or "").strip()
    # Skip the expensive phone scan when the ticket already has an email — the
    # email search alone is enough and runs in < 500 ms.
    match = await match_student(
        email=email or None,
        phone=phone or None,
        name=name or None,
        db=db,
    )
    await db.tickets.update_one(
        {"id": ticket["id"]},
        {"$set": {
            "student_match": match,
            "student_match_at": datetime.now(timezone.utc),
        }},
    )
    ticket["student_match"] = match
    return match
