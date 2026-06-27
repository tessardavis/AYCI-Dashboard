"""
Unified Student Lookup - fan out an email across Monday.com, Circle,
Stripe, ConvertKit, and Calendly and return a normalised profile.

Each `*_lookup` function returns:
    {"found": bool, "data": {...} | None, "error": str | None}

Circle has no email-search endpoint - members list is cached in Mongo
(`circle_members_cache`) and refreshed when older than CACHE_TTL_HOURS.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx

from connectors import (
    CIRCLE_BASE,
    CONVERTKIT_V3,
    STRIPE_API,
    MONDAY_URL,
    CALENDLY_BASE,
    TIMEOUT,
    _circle_headers,
    _ck_secret,
    _stripe_auth,
    _monday_headers,
    _calendly_headers,
    _circle_fetch_all_members,
)

CACHE_TTL_HOURS = 24
ACADEMY_MEMBERS_BOARD_ID = "1956295952"
# Monday column IDs are stable for the life of a board (column re-creation is
# rare and would also require dashboard re-config). Cache the discovered
# email-column ID per board so we skip the schema GraphQL call - that's the
# first of two sequential Monday calls on every cold Student Lookup.
MONDAY_SCHEMA_CACHE_TTL_HOURS = 24


def _normalise(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", "", s.lower())).strip()


def _boss_summary(row):
    """Boss -> testimonial journey status, or None if not a Boss. Lazy import
    avoids a boss_journey import cycle."""
    try:
        from boss_journey import is_boss, journey_status
        return journey_status(row) if is_boss(row) else None
    except Exception:
        return None


def _private_calls_summary(tier, calls, extra=None, boost=None):
    """Allowance view of a student's private-tier (Private Plus / VIP / B&G Plus)
    calls. Lazy import keeps student_lookup free of a calendly_webhook import
    cycle. Returns None for students with no private-tier allowance or calls."""
    try:
        from calendly_webhook import summarize_private_calls
        s = summarize_private_calls(tier, calls, extra, boost)
        return s if s.get("eligible") else None
    except Exception:
        return None


# In-process cache for the Circle members list used by name_search. The Mongo
# document is ~1.7MB and the cross-region read from Atlas takes several
# seconds - well over the 8s frontend timeout on the autocomplete endpoint.
# Read once per process and keep a slim (name + email + avatar) projection in
# memory; everything after the first call is sub-millisecond.
_NAME_INDEX_TTL_SECONDS = 30 * 60  # 30 min
_name_index_cache: dict = {"loaded_at": 0.0, "members": []}


async def _get_name_index(db) -> list[dict]:
    """Returns the full slim member list (name + email + avatar + a few
    other fields) cached in process memory for 30 min.

    Used by both name_search (which only needs name/email/avatar) AND
    circle_lookup (which needs the wider slim shape). One cache, one
    Mongo read per 30 min, regardless of how many lookups happen.

    Reloads early (before the TTL) if the underlying `circle_members_cache.all`
    doc's `cached_at` changed - e.g. someone hit "Refresh Circle cache" or the
    daily 05:00 rebuild ran. Without this, a refresh wouldn't show in the
    Students list (which reads this index) for up to 30 min, and a brand-new
    Circle member keeps showing "get on board first" even after a refresh. The
    freshness probe only pulls `cached_at` (tiny), not the ~1.7MB members blob.
    Cross-worker safe: any worker notices the new cached_at."""
    import time as _time
    now = _time.monotonic()
    try:
        meta = await db.circle_members_cache.find_one({"_id": "all"}, {"_id": 0, "cached_at": 1})
    except Exception:
        meta = None
    doc_cached_at = (meta or {}).get("cached_at")
    if (
        _name_index_cache["members"]
        and (now - _name_index_cache["loaded_at"]) < _NAME_INDEX_TTL_SECONDS
        and _name_index_cache.get("doc_cached_at") == doc_cached_at
    ):
        return _name_index_cache["members"]
    # Load the whole slim doc - circle_lookup needs the extra fields
    # (created_at, last_seen_at, member_tags, profile_url). Memory cost is
    # ~1.7MB once per process; saves us the same 1.7MB Mongo read on
    # every lookup.
    doc = await db.circle_members_cache.find_one({"_id": "all"}, {"_id": 0})
    members = (doc or {}).get("members", []) if doc else []
    _name_index_cache["members"] = members
    _name_index_cache["loaded_at"] = now
    _name_index_cache["doc_cached_at"] = doc_cached_at
    return members


async def name_search(db, query: str, limit: int = 10) -> list[dict]:
    """
    Fuzzy search by name. Looks up Circle's slim member cache (which has
    name+email for ~3.9K students). Returns up to `limit` candidates with
    name, email, avatar so the user can pick the right one.
    """
    if not query or len(query.strip()) < 2:
        return []
    target = _normalise(query)
    parts = target.split()

    members = await _get_name_index(db)
    if not members:
        return []

    scored: list[tuple[int, dict]] = []
    for m in members:
        name = _normalise(m.get("name") or "")
        email = (m.get("email") or "").lower()
        score = 0
        if not name and not email:
            continue
        if target == name:
            score = 100
        elif target in name:
            score = 80
        elif all(p in name.split() for p in parts):
            score = 60
        elif all(p in name for p in parts):
            score = 40
        elif target in email:
            score = 30
        if score:
            scored.append((score, m))

    scored.sort(key=lambda x: -x[0])
    return [
        {
            "name": m.get("name"),
            "email": m.get("email"),
            "avatar_url": m.get("avatar_url"),
            "match_score": s,
        }
        for s, m in scored[:limit]
    ]


# --------------------------------------------------------------------- Stripe
async def stripe_lookup(email: str) -> dict:
    """Find Stripe customer by email + summarise charges and subscriptions."""
    try:
        email_q = email.strip().lower()
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            # Customer search
            r = await c.get(
                f"{STRIPE_API}/customers/search",
                auth=_stripe_auth(),
                params={"query": f'email:"{email_q}"', "limit": 10},
            )
            r.raise_for_status()
            customers = r.json().get("data", [])
            if not customers:
                return {"found": False, "data": None, "error": None}

            # Aggregate across all matching customers
            total_spent = 0
            total_refunded = 0
            charge_count = 0
            last_charge_at: Optional[int] = None
            subs_active: list[dict] = []
            subs_past: list[dict] = []
            customer_links: list[dict] = []
            all_charges: list[dict] = []

            for cust in customers:
                customer_links.append({
                    "id": cust["id"],
                    "url": f"https://dashboard.stripe.com/customers/{cust['id']}",
                    "name": cust.get("name"),
                    "created": cust.get("created"),
                })

            # Charges + subscriptions per customer, all in parallel. Previously
            # 2N sequential GETs (charges → subscriptions, per customer);
            # this collapses to a single gather that takes max(slowest call).
            async def _fetch_charges(cid: str) -> tuple[str, Any]:
                rr = await c.get(
                    f"{STRIPE_API}/charges",
                    auth=_stripe_auth(),
                    params={"customer": cid, "limit": 100},
                )
                return cid, rr

            async def _fetch_subs(cid: str) -> tuple[str, Any]:
                rr = await c.get(
                    f"{STRIPE_API}/subscriptions",
                    auth=_stripe_auth(),
                    params={"customer": cid, "status": "all", "limit": 100},
                )
                return cid, rr

            tasks = []
            for cust in customers:
                tasks.append(_fetch_charges(cust["id"]))
                tasks.append(_fetch_subs(cust["id"]))
            results = await asyncio.gather(*tasks, return_exceptions=True)

            charges_by_cid: dict[str, Any] = {}
            subs_by_cid: dict[str, Any] = {}
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    continue
                cid, rr = res
                # Even indices were charges, odd were subs (per the append order).
                if i % 2 == 0:
                    charges_by_cid[cid] = rr
                else:
                    subs_by_cid[cid] = rr

            for cust in customers:
                cid = cust["id"]
                cr = charges_by_cid.get(cid)
                if cr is not None and cr.status_code == 200:
                    for ch in cr.json().get("data", []):
                        net = int(ch.get("amount", 0)) - int(ch.get("amount_refunded", 0))
                        if ch.get("status") == "succeeded" and not ch.get("refunded") and net > 0:
                            total_spent += int(ch.get("amount", 0))
                            charge_count += 1
                            ct = ch.get("created")
                            if ct and (last_charge_at is None or ct > last_charge_at):
                                last_charge_at = ct
                            all_charges.append({
                                "id": ch.get("id"),
                                "created": (
                                    datetime.fromtimestamp(ch["created"], tz=timezone.utc).isoformat()
                                    if ch.get("created") else None
                                ),
                                "amount": net,
                                "currency": (ch.get("currency") or "gbp").upper(),
                                "description": ch.get("description"),
                                "status": ch.get("status"),
                                "receipt_url": ch.get("receipt_url"),
                                "customer_id": cid,
                            })
                        total_refunded += int(ch.get("amount_refunded", 0))

                sr = subs_by_cid.get(cid)
                if sr is not None and sr.status_code == 200:
                    for s in sr.json().get("data", []):
                        item = (s.get("items", {}).get("data") or [{}])[0]
                        price = item.get("price", {}) or {}
                        plan = {
                            "id": s["id"],
                            "status": s.get("status"),
                            "product_name": (price.get("nickname")
                                             or price.get("product")
                                             or "-"),
                            "amount": (price.get("unit_amount") or 0) / 100.0,
                            "currency": (price.get("currency") or "gbp").upper(),
                            "interval": (price.get("recurring") or {}).get("interval"),
                            "current_period_end": s.get("current_period_end"),
                            "started": s.get("start_date"),
                        }
                        if s.get("status") in ("active", "trialing", "past_due"):
                            subs_active.append(plan)
                        else:
                            subs_past.append(plan)

        return {
            "found": True,
            "data": {
                "customers": customer_links,
                "charges": all_charges,
                "total_spent_gbp": round(total_spent / 100.0, 2),
                "total_refunded_gbp": round(total_refunded / 100.0, 2),
                "charge_count": charge_count,
                "last_charge_at": (datetime.fromtimestamp(last_charge_at, tz=timezone.utc).isoformat()
                                   if last_charge_at else None),
                "active_subscriptions": subs_active,
                "past_subscriptions": subs_past,
            },
            "error": None,
        }
    except Exception as e:
        return {"found": False, "data": None, "error": str(e)}


# ----------------------------------------------------------------- ConvertKit
async def convertkit_lookup(email: str) -> dict:
    """Find subscriber, return status, created_at, and all assigned tags."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(
                f"{CONVERTKIT_V3}/subscribers",
                params={"api_secret": _ck_secret(), "email_address": email.strip().lower()},
            )
            r.raise_for_status()
            subs = r.json().get("subscribers") or []
            if not subs:
                return {"found": False, "data": None, "error": None}
            sub = subs[0]
            sub_id = sub["id"]

            # Fetch tags for this subscriber
            tr = await c.get(
                f"{CONVERTKIT_V3}/subscribers/{sub_id}/tags",
                params={"api_secret": _ck_secret()},
            )
            tags = [{"id": t["id"], "name": t["name"]} for t in tr.json().get("tags", [])] if tr.status_code == 200 else []

        return {
            "found": True,
            "data": {
                "id": sub_id,
                "first_name": sub.get("first_name"),
                "email": sub.get("email_address"),
                "state": sub.get("state"),
                "created_at": sub.get("created_at"),
                "fields": sub.get("fields") or {},
                "tags": tags,
            },
            "error": None,
        }
    except Exception as e:
        return {"found": False, "data": None, "error": str(e)}


# ---------------------------------------------------------------------- Circle
async def _circle_get_cached_members(db) -> tuple[list[dict], str]:
    """Return (members, source) where source is 'cache' or 'fresh'.

    Stores only the fields needed for student lookup to stay well under
    Mongo's 16 MB per-document limit (a full Circle member record is
    several KB; trimmed version is ~200 bytes).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS)
    doc = await db.circle_members_cache.find_one({"_id": "all"}, {"_id": 0})
    if doc:
        cached_at = doc.get("cached_at")
        # Mongo may return naive datetimes - normalise to UTC for comparison
        if isinstance(cached_at, datetime):
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=timezone.utc)
            if cached_at > cutoff:
                return doc.get("members", []), "cache"
    # Refresh
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        raw = await _circle_fetch_all_members(c, sort="created_at", order="desc", max_pages=200)
    slim = [
        {
            "id": m.get("id"),
            "email": (m.get("email") or "").strip().lower(),
            "name": m.get("name"),
            "avatar_url": m.get("avatar_url"),
            "created_at": m.get("created_at"),
            "last_seen_at": m.get("last_seen_at"),
            "member_tags": [t.get("name") for t in (m.get("member_tags") or [])],
            "profile_url": m.get("profile_url") or m.get("public_profile_url"),
        }
        for m in raw
    ]
    await db.circle_members_cache.update_one(
        {"_id": "all"},
        {"$set": {"members": slim, "cached_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return slim, "fresh"


async def circle_lookup(db, email: str) -> dict:
    """Look up a Circle member by email.

    Reads from the in-process members cache (_get_name_index) so we
    don't pull the 1.7MB Mongo doc on every request. The cache itself
    falls back to _circle_get_cached_members on a cold start, which
    handles the 24h Circle-API refresh logic."""
    try:
        target = email.strip().lower()
        # Try the in-process cache first (sub-millisecond once warmed).
        members = await _get_name_index(db)
        source = "in_memory"
        # If the in-memory cache is empty (very first call after a deploy
        # and the Mongo doc is also missing), fall through to the full
        # Mongo-or-refresh path so we don't miss this lookup entirely.
        if not members:
            members, source = await _circle_get_cached_members(db)
        match = next((m for m in members if m.get("email") == target), None)
        if not match:
            return {"found": False, "data": None, "error": None, "cache": source, "total_members_searched": len(members)}
        return {
            "found": True,
            "data": {
                "id": match.get("id"),
                "name": match.get("name"),
                "email": match.get("email"),
                "avatar_url": match.get("avatar_url"),
                "created_at": match.get("created_at"),
                "last_seen_at": match.get("last_seen_at"),
                "member_tags": match.get("member_tags") or [],
                "profile_url": match.get("profile_url"),
            },
            "error": None,
            "cache": source,
        }
    except Exception as e:
        return {"found": False, "data": None, "error": str(e)}


# -------------------------------------------------------------------- Monday
async def _get_monday_email_col_id(db, board_id: str, client: httpx.AsyncClient) -> Optional[str]:
    """Discover the email column ID on a Monday board, with a 24h Mongo cache.
    Returns None if no email column is found (caller falls back to scan)."""
    cache_key = f"monday_schema:{board_id}:email_col"
    cached = await db.fn_cache.find_one({"_id": cache_key}, {"_id": 0, "col_id": 1, "cached_at": 1})
    if cached:
        cached_at = cached.get("cached_at")
        if isinstance(cached_at, datetime):
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(hours=MONDAY_SCHEMA_CACHE_TTL_HOURS)
            if cached_at > cutoff:
                # cached value of None is stored as empty string so we can
                # tell "we checked and there's no email column" apart from
                # "no cache entry yet".
                col_id = cached.get("col_id") or None
                return col_id

    schema_q = f"""
    query {{
      boards(ids: [{int(board_id)}]) {{
        id
        columns {{ id title type }}
      }}
    }}
    """
    r = await client.post(
        MONDAY_URL,
        headers={**_monday_headers(), "Content-Type": "application/json"},
        json={"query": schema_q},
    )
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise RuntimeError(f"Monday GraphQL error: {body['errors']}")
    boards = body.get("data", {}).get("boards") or []
    if not boards:
        return None
    columns = boards[0].get("columns") or []
    email_col = next((col for col in columns
                      if col.get("type") == "email"
                      or "email" in (col.get("title") or "").lower()), None)
    col_id = (email_col or {}).get("id") or ""
    await db.fn_cache.update_one(
        {"_id": cache_key},
        {"$set": {"_id": cache_key, "col_id": col_id, "cached_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return col_id or None


async def monday_lookup(email: str, board_id: str = ACADEMY_MEMBERS_BOARD_ID, name_hint: Optional[str] = None, db=None) -> dict:
    """
    Search the Academy Members board for items whose email column matches.

    Now Mongo-first: tries db.academy_members (the 15-min Monday mirror)
    before falling back to live Monday GraphQL. Saves ~1-3s per lookup
    and removes Monday rate-limit / availability as a request-time
    dependency. The live fallback is kept so callers without a db
    handle, and rows added to Monday since the last 15-min mirror sync,
    still resolve.

    If `name_hint` is provided and the email-based search returns nothing,
    we make a second attempt by searching the `name` column. This handles
    the common case of a student whose Circle/Stripe email differs from
    the email recorded on Monday (e.g. work vs personal address).
    """
    # Mongo-first short-circuit. The mirror stores everything monday_lookup
    # would return - id, name, url, created_at, columns dict - so this is a
    # drop-in for the live-API path.
    if db is not None:
        try:
            import academy_members_mirror
            row = await academy_members_mirror.lookup_by_email(db, email)
            if row:
                cols = row.get("columns") or {}
                cols_by_id = row.get("columns_by_id") or {}
                allowances = _compute_allowances(cols_by_id)
                return {
                    "found": True,
                    "data": {
                        "id": row.get("_id"),
                        "name": row.get("name"),
                        "url": row.get("url"),
                        "created_at": row.get("monday_created_at"),
                        "columns": cols,
                        "allowances": allowances,
                        # Authoritative private-chat link. This scalar is the
                        # merged value - set from Monday's "Private Chat Link"
                        # column OR (more often) recorded by private-chat-setup,
                        # which only ever writes the scalar, never Monday's
                        # column. Callers should prefer this over the raw
                        # columns["Private Chat Link"] text, which is empty for
                        # dashboard-recorded chats.
                        "private_chat_url": row.get("private_chat_url"),
                        # Alt emails so the lookup can retry Calendly/Stripe under
                        # them (students often book/pay with a different email).
                        "email": row.get("email"),
                        "circle_email": row.get("circle_email"),
                        "other_emails": row.get("other_emails"),
                        # Bonus-call booking lifecycle (set by the Calendly webhook
                        # and by coaches via the dashboard).
                        "bonus_call": {
                            "status": row.get("bonus_call_status"),
                            "date": row.get("bonus_call_date"),
                            "coach": row.get("bonus_call_coach"),
                            "rescheduled_from": row.get("bonus_call_rescheduled_from"),
                        },
                        # Private-tier (Private Plus / VIP) 1:1 call allowance +
                        # bookings. tier drives the allowance; private_calls is
                        # the raw list (set by the Calendly webhook + coaches).
                        "tier": row.get("tier"),
                        "private_calls": _private_calls_summary(
                            row.get("tier"), row.get("private_calls"),
                            row.get("private_call_allowance"), row.get("boost_and_go")),
                        # Boss Badge -> testimonial journey (None until they're a
                        # Boss). See PROCESSES.md #5.
                        "boss": _boss_summary(row),
                    },
                    "error": None,
                    "source": "mongo_mirror",
                }
        except Exception as e:
            # Never let a Mongo hiccup block lookups - fall through to live.
            import logging as _logging
            _logging.getLogger(__name__).info(
                f"[student-lookup] mirror lookup failed for {email}, falling back to Monday: {e}"
            )

    try:
        target = email.strip().lower()
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            # Resolve the email column id (24h Mongo-cached). When db is
            # supplied this is one fewer sequential Monday call on the cold
            # path. Without db, fall through to the legacy inline schema
            # fetch so callers that don't have a db handle (cron pre-warm
            # variants) still work.
            email_col_id: Optional[str] = None
            if db is not None:
                try:
                    email_col_id = await _get_monday_email_col_id(db, board_id, c)
                except Exception:
                    email_col_id = None
            if email_col_id is None and db is None:
                schema_q = f"""
                query {{
                  boards(ids: [{int(board_id)}]) {{
                    columns {{ id title type }}
                  }}
                }}
                """
                rs = await c.post(
                    MONDAY_URL,
                    headers={**_monday_headers(), "Content-Type": "application/json"},
                    json={"query": schema_q},
                )
                rs.raise_for_status()
                bs = rs.json()
                cols = ((bs.get("data") or {}).get("boards") or [{}])[0].get("columns") or []
                ec = next((col for col in cols
                           if col.get("type") == "email"
                           or "email" in (col.get("title") or "").lower()), None)
                email_col_id = (ec or {}).get("id")

            items: list[dict] = []
            used_fallback = False

            if email_col_id:
                search_q = """
                query ($boardId: ID!, $colId: String!, $value: String!) {
                  items_page_by_column_values(
                    board_id: $boardId,
                    columns: [{column_id: $colId, column_values: [$value]}],
                    limit: 10
                  ) {
                    items {
                      id
                      name
                      url
                      created_at
                      column_values {
                        id
                        text
                        value
                        type
                        column { title }
                      }
                    }
                  }
                }
                """
                r2 = await c.post(
                    MONDAY_URL,
                    headers={**_monday_headers(), "Content-Type": "application/json"},
                    json={
                        "query": search_q,
                        "variables": {
                            "boardId": str(board_id),
                            "colId": email_col_id,
                            "value": target,
                        },
                    },
                )
                r2.raise_for_status()
                body2 = r2.json()
                if body2.get("errors"):
                    # If the server-side search errors, try fallback
                    used_fallback = True
                else:
                    page = body2.get("data", {}).get("items_page_by_column_values") or {}
                    items = page.get("items") or []
            else:
                # No email column detected - fallback needed
                used_fallback = True

            # Fallback: capped scan (first 500 items only)
            if used_fallback and not items:
                cursor: Optional[str] = None
                scanned = 0
                while scanned < 500:
                    cursor_clause = f', cursor: "{cursor}"' if cursor else ""
                    scan_q = f"""
                    query {{
                      boards(ids: [{int(board_id)}]) {{
                        items_page(limit: 100{cursor_clause}) {{
                          cursor
                          items {{
                            id
                            name
                            url
                            created_at
                            column_values {{ id text value type column {{ title }} }}
                          }}
                        }}
                      }}
                    }}
                    """
                    r3 = await c.post(
                        MONDAY_URL,
                        headers={**_monday_headers(), "Content-Type": "application/json"},
                        json={"query": scan_q},
                    )
                    r3.raise_for_status()
                    b3 = r3.json()
                    if b3.get("errors"):
                        break
                    p = (b3.get("data", {}).get("boards") or [{}])[0].get("items_page") or {}
                    batch = p.get("items") or []
                    for it in batch:
                        for col in it.get("column_values") or []:
                            if col.get("type") == "email":
                                txt = (col.get("text") or "").strip().lower()
                                if txt == target:
                                    items.append(it)
                                    break
                    scanned += len(batch)
                    cursor = p.get("cursor")
                    if not cursor or not batch or items:
                        break

            # Name-based fallback: when the caller supplied a name hint and the
            # email-based search returned nothing, try matching the Monday
            # `name` column. Helps when a student's Circle / Stripe email
            # doesn't match the email recorded on Monday.
            if not items and name_hint:
                name_q = """
                query ($boardId: ID!, $value: String!) {
                  items_page_by_column_values(
                    board_id: $boardId,
                    columns: [{column_id: "name", column_values: [$value]}],
                    limit: 5
                  ) {
                    items {
                      id name url created_at
                      column_values { id text value type column { title } }
                    }
                  }
                }
                """
                try:
                    rn = await c.post(
                        MONDAY_URL,
                        headers={**_monday_headers(), "Content-Type": "application/json"},
                        json={
                            "query": name_q,
                            "variables": {"boardId": str(board_id), "value": name_hint.strip()},
                        },
                    )
                    rn.raise_for_status()
                    bn = rn.json()
                    if not bn.get("errors"):
                        page = bn.get("data", {}).get("items_page_by_column_values") or {}
                        items = page.get("items") or []
                except Exception:
                    pass

        if not items:
            return {"found": False, "data": None, "error": None}

        item = items[0]
        cols: dict[str, Any] = {}
        cols_by_id: dict[str, dict] = {}
        for col in item.get("column_values") or []:
            cid = col.get("id")
            title = (col.get("column") or {}).get("title")
            entry = {
                "text": col.get("text"),
                "type": col.get("type"),
            }
            if title:
                cols[title] = entry
            if cid:
                cols_by_id[cid] = {**entry, "title": title}

        # Compute coach-friendly allowance summary (calls, mocks, bonus, videos)
        allowances = _compute_allowances(cols_by_id)

        return {
            "found": True,
            "data": {
                "id": item.get("id"),
                "name": item.get("name"),
                "url": item.get("url"),
                "created_at": item.get("created_at"),
                "columns": cols,
                "allowances": allowances,
            },
            "error": None,
        }
    except Exception as e:
        return {"found": False, "data": None, "error": str(e)}


def _compute_allowances(cols_by_id: dict[str, dict]) -> dict:
    """Reuse upcoming_interviews allowance logic for the Student Lookup card."""
    try:
        from upcoming_interviews import (
            CALL_COLS, MOCK_COLS, BONUS_COLS,
            COL_VIDEO_ALLOWANCE, COL_VIDEOS_SUBMITTED,
            _allowance,
        )
    except Exception:
        return {}

    calls = _allowance(cols_by_id, CALL_COLS)
    mocks = _allowance(cols_by_id, MOCK_COLS)
    bonus = _allowance(cols_by_id, BONUS_COLS)

    video_allowance_raw = (cols_by_id.get(COL_VIDEO_ALLOWANCE) or {}).get("text") or ""
    video_used_raw = (cols_by_id.get(COL_VIDEOS_SUBMITTED) or {}).get("text") or ""
    try:
        video_allowance = int(float(video_allowance_raw)) if video_allowance_raw else 0
    except ValueError:
        video_allowance = 0
    try:
        video_used = int(float(video_used_raw)) if video_used_raw else 0
    except ValueError:
        video_used = 0

    return {
        "calls_30min": calls,
        "mock_interviews": mocks,
        "bonus_calls": bonus,
        "videos": {
            "submitted": video_used,
            "allowance": video_allowance,
            "remaining": max(0, video_allowance - video_used),
        },
    }


# ------------------------------------------------------------------ Calendly
async def calendly_lookup(email: str) -> dict:
    """Return past + upcoming scheduled events for this email, with host info."""
    try:
        target = email.strip().lower()
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            me = await c.get(f"{CALENDLY_BASE}/users/me", headers=_calendly_headers())
            me.raise_for_status()
            org = me.json().get("resource", {}).get("current_organization")
            if not org:
                return {"found": False, "data": None, "error": "No Calendly organization"}

            events: list[dict] = []
            page_token: Optional[str] = None
            while True:
                q: dict[str, Any] = {
                    "organization": org,
                    "invitee_email": target,
                    "count": 50,
                    "sort": "start_time:desc",
                }
                if page_token:
                    q["page_token"] = page_token
                r = await c.get(f"{CALENDLY_BASE}/scheduled_events", headers=_calendly_headers(), params=q)
                if r.status_code != 200:
                    break
                body = r.json()
                for ev in body.get("collection", []):
                    # Pull host name from event_memberships (host is the AYCI side).
                    membs = ev.get("event_memberships") or []
                    host_name = None
                    host_email = None
                    if membs:
                        host_name = membs[0].get("user_name") or membs[0].get("user")
                        host_email = membs[0].get("user_email")
                    events.append({
                        "uri": ev.get("uri"),
                        "name": ev.get("name"),
                        "start_time": ev.get("start_time"),
                        "end_time": ev.get("end_time"),
                        "status": ev.get("status"),
                        "host_name": host_name,
                        "host_email": host_email,
                        "location": (ev.get("location") or {}).get("join_url") or (ev.get("location") or {}).get("location"),
                    })
                page_token = (body.get("pagination") or {}).get("next_page_token")
                if not page_token or len(events) >= 100:
                    break

        if not events:
            return {"found": False, "data": None, "error": None}

        # Split into past + upcoming relative to now (UTC)
        now_iso = datetime.now(timezone.utc).isoformat()
        past = [e for e in events if (e.get("start_time") or "") < now_iso and e.get("status") == "active"]
        upcoming = [e for e in events if (e.get("start_time") or "") >= now_iso and e.get("status") == "active"]
        cancelled = [e for e in events if e.get("status") != "active"]

        return {
            "found": True,
            "data": {
                "past": past,
                "upcoming": upcoming,
                "cancelled": cancelled,
                "events": events,  # full chronological list (kept for back-compat)
                "total": len(events),
            },
            "error": None,
        }
    except Exception as e:
        return {"found": False, "data": None, "error": str(e)}
