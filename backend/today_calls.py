"""Today's Calls — unified view of every call happening in the next ~24 h.

Sources:
  • Calendly (read-only, the source of truth for 95% of bookings)
  • `manual_calls` collection — short ad-hoc entries the team adds when a
    student reschedules via DM and there's no Calendly event for it.

Each call is pre-warmed for Drive doc summaries (see upcoming_call_prewarm)
so when the coach clicks "Open lookup" right before the call, the AI
summary comes from cache instantly.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

CALENDLY_BASE = "https://api.calendly.com"
LONDON = ZoneInfo("Europe/London")


def _calendly_headers() -> dict:
    return {"Authorization": f"Bearer {os.environ.get('CALENDLY_TOKEN', '')}"}


async def _calendly_today_events(now_utc: datetime) -> list[dict]:
    """All active Calendly events whose start time falls on TODAY (UK time)
    plus any that have already started but haven't finished yet."""
    if not os.environ.get("CALENDLY_TOKEN"):
        return []

    # UK day-window converted back to UTC for the query
    today_uk = now_utc.astimezone(LONDON).date()
    start_uk = datetime.combine(today_uk, datetime.min.time(), tzinfo=LONDON)
    end_uk = start_uk + timedelta(days=1)
    start_iso = start_uk.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    end_iso = end_uk.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    out: list[dict] = []
    async with httpx.AsyncClient(timeout=20.0) as c:
        try:
            me = await c.get(f"{CALENDLY_BASE}/users/me", headers=_calendly_headers())
            org = me.json().get("resource", {}).get("current_organization")
            if not org:
                return []
            evs_resp = await c.get(
                f"{CALENDLY_BASE}/scheduled_events",
                headers=_calendly_headers(),
                params={
                    "organization": org,
                    "min_start_time": start_iso,
                    "max_start_time": end_iso,
                    "status": "active",
                    "count": 100,
                    "sort": "start_time:asc",
                },
            )
            events = evs_resp.json().get("collection", []) or []
        except Exception as e:
            logger.warning(f"[today-calls] Calendly fetch failed: {e}")
            return []

        for ev in events:
            uri = ev.get("uri") or ""
            uuid_ev = uri.rsplit("/", 1)[-1]
            try:
                inv_resp = await c.get(
                    f"{CALENDLY_BASE}/scheduled_events/{uuid_ev}/invitees",
                    headers=_calendly_headers(),
                )
                invitees = inv_resp.json().get("collection", []) or []
            except Exception:
                invitees = []
            host = ((ev.get("event_memberships") or [{}])[0]).get("user_name") or "?"
            try:
                s = datetime.fromisoformat((ev.get("start_time") or "").replace("Z", "+00:00"))
                e = datetime.fromisoformat((ev.get("end_time") or "").replace("Z", "+00:00"))
                duration_min = int((e - s).total_seconds() // 60)
            except Exception:
                duration_min = 30
            for inv in invitees:
                em = (inv.get("email") or "").strip().lower()
                nm = (inv.get("name") or "").strip()
                if not em:
                    continue
                out.append({
                    "id": f"cal_{uuid_ev}_{em}",
                    "source": "calendly",
                    "starts_at": ev.get("start_time"),
                    "duration_min": duration_min,
                    "host": host,
                    "student_name": nm,
                    "student_email": em,
                    "event_type": ev.get("name") or "",
                    "calendly_event_uri": uri,
                })
    return out


async def list_today_calls(db, *, now_utc: datetime | None = None) -> list[dict]:
    """Merge Calendly + manual_calls, sorted by start time (asc), enriched
    with tier/speciality/interview-date pulled from the upcoming_interviews
    feed so the UI can show a VIP/Academy badge per row."""
    now_utc = now_utc or datetime.now(timezone.utc)
    today_uk = now_utc.astimezone(LONDON).date()
    start_uk = datetime.combine(today_uk, datetime.min.time(), tzinfo=LONDON)
    end_uk = start_uk + timedelta(days=1)

    cal = await _calendly_today_events(now_utc)
    manual_cursor = db.manual_calls.find(
        {
            "starts_at": {
                "$gte": start_uk.astimezone(timezone.utc).isoformat(),
                "$lt": end_uk.astimezone(timezone.utc).isoformat(),
            },
        },
        {"_id": 0},
    )
    manual: list[dict] = []
    async for m in manual_cursor:
        m["source"] = "manual"
        manual.append(m)

    everything = cal + manual
    everything.sort(key=lambda x: x.get("starts_at") or "")

    # Enrich with tier / speciality / interview date from the upcoming_interviews
    # feed (sourced from Monday). Single fetch covers academy + private tiers.
    try:
        import upcoming_interviews as upc
        roster = await upc.fetch_upcoming_interviews(db=db, days=60)
        tier_by_email: dict[str, dict] = {}
        for s in (roster.get("academy") or []) + (roster.get("private") or []):
            em = (s.get("email") or "").strip().lower()
            if em:
                tier_by_email[em] = {
                    "tier": s.get("tier"),
                    "tier_group": s.get("tier_group"),
                    "speciality": s.get("speciality"),
                    "interview_date": s.get("interview_date"),
                }
        for c in everything:
            extra = tier_by_email.get((c.get("student_email") or "").lower())
            if extra:
                c.update(extra)
    except Exception as e:
        logger.info(f"[today-calls] tier enrichment skipped: {e}")

    return everything


async def add_manual_call(
    db,
    *,
    student_name: str,
    student_email: str,
    host: str,
    starts_at: str,  # ISO-8601 UTC
    duration_min: int = 30,
    notes: str | None = None,
    created_by: str | None = None,
) -> dict:
    row = {
        "id": str(uuid.uuid4()),
        "student_name": student_name.strip(),
        "student_email": student_email.strip().lower(),
        "host": host.strip(),
        "starts_at": starts_at,
        "duration_min": int(duration_min or 30),
        "notes": (notes or "").strip() or None,
        "event_type": "Manual entry",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": created_by,
    }
    await db.manual_calls.insert_one(dict(row))
    # Fire-and-forget pre-warm so by the time the coach opens the lookup
    # the Drive summary is cached.
    try:
        import asyncio
        import google_drive as gdrive
        asyncio.create_task(
            gdrive.summarise_student_doc(db, row["student_name"], row["student_email"])
        )
    except Exception as e:
        logger.warning(f"[today-calls] manual prewarm fire failed: {e}")
    return {**row, "source": "manual"}


async def delete_manual_call(db, call_id: str) -> dict:
    res = await db.manual_calls.delete_one({"id": call_id})
    return {"ok": True, "deleted": res.deleted_count}
