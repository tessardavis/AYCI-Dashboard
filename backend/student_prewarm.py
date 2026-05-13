"""Pre-warm the unified Student Lookup cache for every private-tier student.

Runs at 05:30 UK daily. Coaches open private-tier students 10x more often
than Academy ones (private coaching sessions, weekly 1:1s, group sessions,
prep calls, etc.) — warming the cache means the first open of the day is
instant instead of a 3-8s parallel fan-out across Monday/Circle/Stripe/
ConvertKit/Calendly/Tally.

Scope: "private tier" = every Academy Members row whose Tier dropdown is
something *other than* plain "Academy" / "Silver" / "Gold" (legacy
Academy-equivalent labels). We mirror the definition used in
`upcoming_interviews.py` to keep tier classification consistent dashboard-wide.

Throttling: process students in batches of 6 with a 1s pause between batches
so we never hammer Stripe/ConvertKit/Calendly rate limits in the warm-up.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import httpx

from connectors import MONDAY_URL, _monday_headers, TIMEOUT
from student_match import ACADEMY_MEMBERS_BOARD_ID, COL_EMAIL, COL_TIER, _txt

logger = logging.getLogger(__name__)

# Tier labels that we treat as plain Academy (NOT pre-warmed). Everything
# else is private-tier.
ACADEMY_EQUIV = {"academy", "silver", "gold"}

BATCH_SIZE = 6
BATCH_PAUSE_SECONDS = 1.0


async def _fetch_private_tier_students() -> list[dict]:
    """Page through the Academy Members board, return rows with a non-Academy
    tier dropdown. Each row = {item_id, name, email, tier}."""
    q = """
    query ($boardId: ID!, $limit: Int!, $cursor: String) {
      boards(ids: [$boardId]) {
        items_page(limit: $limit, cursor: $cursor) {
          cursor
          items {
            id name
            column_values { id text }
          }
        }
      }
    }
    """
    out: list[dict] = []
    cursor: Optional[str] = None
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        # Cap at ~5000 students to be safe (board is ~3.5K today).
        for _ in range(60):
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
            page = (body.get("data") or {}).get("boards", [{}])[0].get("items_page") or {}
            items = page.get("items") or []
            for it in items:
                cols = it.get("column_values") or []
                email = (_txt(cols, COL_EMAIL) or "").strip().lower()
                tier = (_txt(cols, COL_TIER) or "").strip()
                if not email:
                    continue
                # Match the private-tier definition used in upcoming_interviews.py
                tier_parts = [t.strip().lower() for t in tier.split(",") if t.strip()]
                is_pure_academy = (not tier_parts) or all(
                    tp in ACADEMY_EQUIV for tp in tier_parts
                )
                if is_pure_academy:
                    continue
                out.append({
                    "item_id": it.get("id"),
                    "name": it.get("name"),
                    "email": email,
                    "tier": tier,
                })
            cursor = page.get("cursor")
            if not cursor or not items:
                break
    return out


async def prewarm_private_tier_lookups(db) -> dict:
    """Run the unified lookup for every private-tier student and persist
    the result into `student_lookup_cache`. Returns a summary dict."""
    # Lazy-import to avoid circular import at module load (routes.students
    # also imports modules that import this file via the prewarm cron).
    from routes.students import _run_lookup_fanout, _write_lookup_cache

    started = time.monotonic()
    students = await _fetch_private_tier_students()
    logger.info(f"[prewarm] {len(students)} private-tier students to warm")

    ok = 0
    failed = 0
    skipped = 0
    for i in range(0, len(students), BATCH_SIZE):
        batch = students[i : i + BATCH_SIZE]

        async def _one(s: dict) -> tuple[bool, bool]:
            try:
                payload = await _run_lookup_fanout(s["email"], name=s.get("name"))
                await _write_lookup_cache(s["email"], payload)
                return True, False
            except Exception as e:
                logger.warning(f"[prewarm] {s['email']}: {e}")
                return False, False

        results = await asyncio.gather(*(_one(s) for s in batch), return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                failed += 1
                continue
            success, was_skipped = r
            if was_skipped:
                skipped += 1
            elif success:
                ok += 1
            else:
                failed += 1
        await asyncio.sleep(BATCH_PAUSE_SECONDS)

    elapsed = round(time.monotonic() - started, 1)
    return {
        "total": len(students),
        "warmed": ok,
        "failed": failed,
        "skipped": skipped,
        "elapsed_seconds": elapsed,
    }
