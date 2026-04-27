"""
Unified Student Lookup — fan out an email across Monday.com, Circle,
Stripe, ConvertKit, and Calendly and return a normalised profile.

Each `*_lookup` function returns:
    {"found": bool, "data": {...} | None, "error": str | None}

Circle has no email-search endpoint — members list is cached in Mongo
(`circle_members_cache`) and refreshed when older than CACHE_TTL_HOURS.
"""
from __future__ import annotations

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


def _normalise(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", "", s.lower())).strip()


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

    doc = await db.circle_members_cache.find_one({"_id": "all"}, {"_id": 0})
    if not doc:
        return []
    members = doc.get("members", [])

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

            for cust in customers:
                cid = cust["id"]
                customer_links.append({
                    "id": cid,
                    "url": f"https://dashboard.stripe.com/customers/{cid}",
                    "name": cust.get("name"),
                    "created": cust.get("created"),
                })

                # Charges
                cr = await c.get(
                    f"{STRIPE_API}/charges",
                    auth=_stripe_auth(),
                    params={"customer": cid, "limit": 100},
                )
                if cr.status_code == 200:
                    for ch in cr.json().get("data", []):
                        if ch.get("status") == "succeeded" and not ch.get("refunded"):
                            total_spent += int(ch.get("amount", 0))
                            charge_count += 1
                            ct = ch.get("created")
                            if ct and (last_charge_at is None or ct > last_charge_at):
                                last_charge_at = ct
                        total_refunded += int(ch.get("amount_refunded", 0))

                # Subscriptions
                sr = await c.get(
                    f"{STRIPE_API}/subscriptions",
                    auth=_stripe_auth(),
                    params={"customer": cid, "status": "all", "limit": 100},
                )
                if sr.status_code == 200:
                    for s in sr.json().get("data", []):
                        item = (s.get("items", {}).get("data") or [{}])[0]
                        price = item.get("price", {}) or {}
                        plan = {
                            "id": s["id"],
                            "status": s.get("status"),
                            "product_name": (price.get("nickname")
                                             or price.get("product")
                                             or "—"),
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
        # Mongo may return naive datetimes — normalise to UTC for comparison
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
    try:
        target = email.strip().lower()
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
async def monday_lookup(email: str, board_id: str = ACADEMY_MEMBERS_BOARD_ID) -> dict:
    """
    Search the Academy Members board for items whose email column matches.
    Uses items_page_by_column_values for server-side filtering. Falls back
    to a capped scan only if the email column can't be discovered.
    """
    try:
        target = email.strip().lower()
        schema_q = f"""
        query {{
          boards(ids: [{int(board_id)}]) {{
            id
            name
            columns {{ id title type }}
          }}
        }}
        """
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(
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
                return {"found": False, "data": None, "error": "board not found"}
            columns = boards[0].get("columns") or []
            email_col = next((col for col in columns
                              if col.get("type") == "email"
                              or "email" in (col.get("title") or "").lower()), None)

            items: list[dict] = []
            used_fallback = False

            if email_col:
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
                            "colId": email_col["id"],
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
                # No email column detected — fallback needed
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
    """Return past scheduled events for this email."""
    try:
        target = email.strip().lower()
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            me = await c.get(f"{CALENDLY_BASE}/users/me", headers=_calendly_headers())
            me.raise_for_status()
            org = me.json().get("resource", {}).get("current_organization")
            if not org:
                return {"found": False, "data": None, "error": "No Calendly organization"}

            # Calendly: list invitees by email across the organization
            events: list[dict] = []
            page_token: Optional[str] = None
            while True:
                q: dict[str, Any] = {
                    "organization": org,
                    "invitee_email": target,
                    "count": 50,
                    "status": "active",
                    "sort": "start_time:desc",
                }
                if page_token:
                    q["page_token"] = page_token
                r = await c.get(f"{CALENDLY_BASE}/scheduled_events", headers=_calendly_headers(), params=q)
                if r.status_code != 200:
                    break
                body = r.json()
                for ev in body.get("collection", []):
                    events.append({
                        "uri": ev.get("uri"),
                        "name": ev.get("name"),
                        "start_time": ev.get("start_time"),
                        "end_time": ev.get("end_time"),
                        "status": ev.get("status"),
                        "location": (ev.get("location") or {}).get("join_url") or (ev.get("location") or {}).get("location"),
                    })
                page_token = (body.get("pagination") or {}).get("next_page_token")
                if not page_token or len(events) >= 100:
                    break

        if not events:
            return {"found": False, "data": None, "error": None}
        return {"found": True, "data": {"events": events, "total": len(events)}, "error": None}
    except Exception as e:
        return {"found": False, "data": None, "error": str(e)}
