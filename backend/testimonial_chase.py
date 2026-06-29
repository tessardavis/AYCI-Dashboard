"""
Dashboard-driven testimonial chase - replaces the legacy Circle-badge → Zapier →
Monday "Student Wins Tracker" (5095636561) → Zapier-DM chain (which broke ~16 Jun
2026). See PROCESSES.md #5.

How it works now:
  - When Coralie marks someone a Boss (or the success form fires mark-boss-by-email),
    `_apply_boss` stamps `testimonial_chase_started_at`. ONLY rows with that stamp
    are chased - so existing/legacy Bosses are never retro-blasted (Coralie clears
    that backlog by hand).
  - This scheduler sends a first DM + 3 follow-ups across ~30 days by POSTing to a
    Zapier catch-hook, which sends the Circle DM from Coralie's account (the same
    senders the Monday flow used - just triggered here instead of by Monday).
  - It STOPS the moment the student books (Calendly, already detected), the call is
    recorded, the student replies (inbound Circle DM bot, or a manual toggle), or
    all 4 messages have gone.

Safety: OFF by default (settings.enabled). Sends at most ONE message per student per
run. Idempotent on `testimonial_chase_step`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

import settings_store
from boss_journey import is_boss, journey_status

logger = logging.getLogger(__name__)

# Offsets (days from chase start) for message 1, 2, 3, 4. First goes out on the
# next run after marking; follow-ups across ~30 days. One-line to retune.
CHASE_OFFSETS_DAYS = [0, 7, 16, 30]


def _parse_dt(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _stop_reason(row: dict) -> str | None:
    """Why the chase should stop for this row, or None to keep going."""
    j = journey_status(row)
    if j["testimonial_recorded"]:
        return "recorded"
    if j["testimonial_booked"]:
        return "booked"
    if row.get("testimonial_replied_at"):
        return "replied"
    if int(row.get("testimonial_chase_step") or 0) >= len(CHASE_OFFSETS_DAYS):
        return "complete"
    return None


async def _send_message(db, row: dict, message_number: int, url: str) -> bool:
    payload = {
        "event": "testimonial_chase",
        "message_number": message_number,          # 1..4
        "is_first": message_number == 1,
        "student_id": row.get("_id"),
        "name": row.get("name"),
        "first_name": row.get("first_name"),
        "email": (row.get("email") or "").strip().lower(),
        "circle_email": (row.get("circle_email") or "").strip().lower(),
        "boss_tagged_at": str(row.get("boss_tagged_at") or ""),
    }
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(url, json=payload)
        if r.status_code not in (200, 201, 202, 204):
            logger.warning(f"[testimonial-chase] webhook {r.status_code} for {row.get('_id')}: {r.text[:160]}")
            return False
    except Exception as e:
        logger.warning(f"[testimonial-chase] webhook errored for {row.get('_id')}: {e}")
        return False
    return True


async def run_chase(db) -> dict:
    """Scheduled sweep: stop finished chases, send the next due message (one per
    student per run). No-op unless enabled + a webhook is configured."""
    cfg = await settings_store.get_testimonial_chase_config(db)
    summary = {"enabled": cfg["enabled"], "checked": 0, "sent": 0, "stopped": 0, "skipped_no_webhook": False}
    if not cfg["enabled"]:
        return summary
    url = cfg["webhook_url"]
    if not url:
        summary["skipped_no_webhook"] = True
        return summary

    now = datetime.now(timezone.utc)
    cursor = db.academy_members.find(
        {"testimonial_chase_started_at": {"$nin": [None, ""]},
         "testimonial_chase_stopped_at": {"$in": [None, ""]}},
        {"name": 1, "first_name": 1, "email": 1, "circle_email": 1,
         "boss_badge": 1, "boss_tagged_at": 1, "win_shared_at": 1,
         "testimonial_status": 1, "testimonial_booked_date": 1,
         "testimonial_recorded_at": 1, "testimonial_replied_at": 1,
         "testimonial_chase_started_at": 1, "testimonial_chase_step": 1},
    )
    async for row in cursor:
        summary["checked"] += 1
        if not is_boss(row):
            continue
        reason = _stop_reason(row)
        if reason:
            await db.academy_members.update_one({"_id": row["_id"]}, {"$set": {
                "testimonial_chase_stopped_at": now,
                "testimonial_chase_stopped_reason": reason}})
            summary["stopped"] += 1
            continue
        step = int(row.get("testimonial_chase_step") or 0)  # messages already sent
        started = _parse_dt(row.get("testimonial_chase_started_at"))
        if started is None:
            continue
        due_at = started + timedelta(days=CHASE_OFFSETS_DAYS[step])
        if now < due_at:
            continue  # next message not due yet
        if await _send_message(db, row, step + 1, url):
            await db.academy_members.update_one({"_id": row["_id"]}, {"$set": {
                "testimonial_chase_step": step + 1,
                "testimonial_chase_last_sent_at": now}})
            summary["sent"] += 1
    logger.info(f"[testimonial-chase] {summary}")
    return summary


async def mark_replied(db, *, email: str | None = None, student_id=None) -> dict:
    """Mark a Boss as having replied → stops the chase. Called by the inbound
    Circle DM bot and by a manual control."""
    now = datetime.now(timezone.utc)
    q = None
    if student_id is not None:
        q = {"_id": student_id}
    elif email:
        e = email.strip().lower()
        q = {"$or": [{"email": e}, {"circle_email": e}]}
    if not q:
        return {"ok": False, "error": "email or student_id required"}
    res = await db.academy_members.update_one(
        {**q, "testimonial_chase_started_at": {"$nin": [None, ""]},
         "testimonial_chase_stopped_at": {"$in": [None, ""]}},
        {"$set": {"testimonial_replied_at": now,
                  "testimonial_chase_stopped_at": now,
                  "testimonial_chase_stopped_reason": "replied"}})
    return {"ok": True, "matched": res.matched_count, "modified": res.modified_count}
