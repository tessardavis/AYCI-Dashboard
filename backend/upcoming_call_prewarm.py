"""Pre-warm Drive doc summaries for students with upcoming Calendly calls.

The Coach Activity / Student Lookup flow is `email → drive doc → AI summary`,
which takes 10-20s the first time we touch a student's doc. The team almost
always wants to look up a student RIGHT BEFORE their call - so we pre-fetch
the Drive summary for every student with a Calendly event in the next 36
hours. By the time Anoop opens Fiona's lookup at 8:55am, the summary is
already in the cache and renders instantly.

Scheduled via APScheduler - runs every hour at :05 UK time.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

CALENDLY_BASE = "https://api.calendly.com"
WINDOW_HOURS = 36
CONCURRENCY = 3  # cap parallel Drive lookups so we don't thrash the API


def _calendly_headers() -> dict:
    return {"Authorization": f"Bearer {os.environ.get('CALENDLY_TOKEN', '')}"}


async def _list_upcoming_invitees(window_hours: int = WINDOW_HOURS) -> list[dict]:
    """Pull every active Calendly event in the next N hours, return one
    record per invitee: {email, name, host, starts_at}."""
    if not os.environ.get("CALENDLY_TOKEN"):
        return []
    now = datetime.now(timezone.utc)
    start = now.isoformat().replace("+00:00", "Z")
    end = (now + timedelta(hours=window_hours)).isoformat().replace("+00:00", "Z")

    out: list[dict] = []
    async with httpx.AsyncClient(timeout=30.0) as c:
        try:
            me = await c.get(f"{CALENDLY_BASE}/users/me", headers=_calendly_headers())
            org = me.json().get("resource", {}).get("current_organization")
            if not org:
                return []
            events_resp = await c.get(
                f"{CALENDLY_BASE}/scheduled_events",
                headers=_calendly_headers(),
                params={
                    "organization": org,
                    "min_start_time": start,
                    "max_start_time": end,
                    "status": "active",
                    "count": 100,
                    "sort": "start_time:asc",
                },
            )
            events = events_resp.json().get("collection", []) or []
        except Exception as e:
            logger.warning(f"[prewarm] Calendly fetch failed: {e}")
            return []

        # Pull invitees for each event in parallel-ish (batched)
        async def _invitees_for(ev: dict) -> list[dict]:
            uri = ev.get("uri") or ""
            uuid = uri.rsplit("/", 1)[-1]
            host = ((ev.get("event_memberships") or [{}])[0]).get("user_name") or "?"
            starts_at = ev.get("start_time") or ""
            try:
                r = await c.get(
                    f"{CALENDLY_BASE}/scheduled_events/{uuid}/invitees",
                    headers=_calendly_headers(),
                )
                invitees = r.json().get("collection", []) or []
            except Exception:
                return []
            return [
                {
                    "email": (i.get("email") or "").strip().lower(),
                    "name": i.get("name") or "",
                    "host": host,
                    "starts_at": starts_at,
                }
                for i in invitees
                if i.get("email")
            ]

        results = await asyncio.gather(*(_invitees_for(e) for e in events), return_exceptions=True)
        for r in results:
            if isinstance(r, list):
                out.extend(r)

    # De-dupe by email - one student may have multiple events in the window
    by_email: dict[str, dict] = {}
    for inv in out:
        em = inv["email"]
        if em not in by_email or (inv["starts_at"] < by_email[em]["starts_at"]):
            by_email[em] = inv  # keep the soonest call
    return list(by_email.values())


async def prewarm_upcoming_calls(db) -> dict:
    """Top-level entry called by the scheduler. Returns counts for logging."""
    invitees = await _list_upcoming_invitees()
    if not invitees:
        return {"candidates": 0, "warmed": 0}

    # Lazy-import so module-load time stays cheap
    import google_drive as gdrive

    sem = asyncio.Semaphore(CONCURRENCY)
    warmed = 0
    failed = 0

    async def _warm_one(inv: dict) -> None:
        nonlocal warmed, failed
        async with sem:
            try:
                await gdrive.summarise_student_doc(db, inv["name"], inv["email"])
                warmed += 1
                logger.info(f"[prewarm] warmed {inv['email']} (call with {inv['host']} @ {inv['starts_at'][:16]})")
            except Exception as e:
                failed += 1
                logger.info(f"[prewarm] {inv['email']} skipped: {e}")

    await asyncio.gather(*(_warm_one(inv) for inv in invitees), return_exceptions=True)
    return {"candidates": len(invitees), "warmed": warmed, "failed": failed}
