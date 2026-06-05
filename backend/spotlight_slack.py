"""
Spotlight session reminders → Slack.

Posts a prioritised digest to the existing `SLACK_WEBHOOK_URL` 30 minutes
before each upcoming Curriculum / General Coaching session. Tracked in Mongo
collection `spotlight_reminders_sent` so each session triggers exactly once.

Triggered every 5 minutes by an APScheduler cron in server.py.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

import spotlight

logger = logging.getLogger(__name__)

UK_TZ = ZoneInfo("Europe/London")


def _webhook_url() -> Optional[str]:
    url = (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()
    return url or None


def _relative_time_phrase(starts_at: datetime, now: datetime) -> str:
    """Return a human phrase like "starts in 28 min", "in progress", or
    "started 45 min ago", computed from `starts_at` vs `now` (both UTC)."""
    delta_min = int((starts_at - now).total_seconds() / 60)
    if delta_min >= 1:
        if delta_min >= 90:
            hours = round(delta_min / 60, 1)
            return f"starts in {hours:g} h"
        return f"starts in {delta_min} min"
    if delta_min <= -1:
        ago = -delta_min
        if ago >= 90:
            hours = round(ago / 60, 1)
            return f"started {hours:g} h ago"
        return f"started {ago} min ago"
    return "starting now"


def _format_session_blocks(session: dict, *, now: Optional[datetime] = None) -> dict:
    """Build the Slack block payload for a single session."""
    name = session.get("name") or "Spotlight session"
    starts_at_iso = session.get("starts_at") or ""
    now_utc = now or datetime.now(timezone.utc)
    uk_label = "—"
    relative = "(time unknown)"
    try:
        start_dt = datetime.fromisoformat(starts_at_iso.replace("Z", "+00:00"))
        uk_local = start_dt.astimezone(UK_TZ)
        uk_label = uk_local.strftime("%a %d %b · %H:%M") + " UK"
        relative = _relative_time_phrase(start_dt, now_utc)
    except ValueError:
        pass

    students = session.get("students") or []
    eligible = [s for s in students if s.get("eligible")]
    header = (
        f"*🎯 Spotlight prep · {name}*\n"
        f"_{relative.capitalize()} · {uk_label}_\n"
        f"*{len(students)} submission{'' if len(students) == 1 else 's'}*"
        f" · {len(eligible)} eligible (submitted on {session.get('deadline_uk_date') or 'the day before'})"
        f" · {session.get('with_interview_total', 0)} have interviews soon"
    )

    if not students:
        return {
            "text": f"Spotlight reminder: {name} starts in 30 min — no submissions.",
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": header}},
                {"type": "context", "elements": [
                    {"type": "mrkdwn", "text": ":white_check_mark: No spotlight signups for this one — open mic if you want."},
                ]},
            ],
        }

    lines = []
    for i, s in enumerate(students[:8], 1):
        name_label = s.get("name") or "(unknown)"
        topic = (s.get("topic") or "(no topic)")[:120]
        ix_date = s.get("interview_date")
        days = s.get("days_until_interview")
        score = s.get("leaderboard_score")
        meta = []
        if ix_date and days is not None:
            soon_emoji = ":rotating_light: " if days <= 7 else ""
            meta.append(f"{soon_emoji}interview {ix_date} (in {days}d)")
        if score:
            meta.append(f":star: {score} badges")
        if not s.get("eligible"):
            why = s.get("eligibility")
            if why == "late":
                meta.append(":hourglass_flowing_sand: late")
            elif why == "early":
                meta.append(":calendar: too early")
            else:
                meta.append(":grey_question: not eligible")
        meta_str = (" · " + " · ".join(meta)) if meta else ""
        lines.append(f"{i}. *{name_label}* — _{topic}_{meta_str}")

    if len(students) > 8:
        lines.append(f"_…and {len(students) - 8} more_")

    body_block = {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}

    board_url = (os.environ.get("SPOTLIGHT_BOARD_URL") or "").strip()
    if not board_url:
        # Default to the live dashboard's /spotlight page (Vercel frontend).
        # Override with SPOTLIGHT_BOARD_URL if the domain changes.
        board_url = "https://ayci-dashboard-nfiw.vercel.app/spotlight"

    actions = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"<{board_url}|Open Spotlight Coaching board →>"},
        }
    ]

    return {
        "text": f"Spotlight reminder: {name} starts in ~30 min ({len(students)} signups).",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
            body_block,
            *actions,
        ],
    }


async def _post_to_slack(payload: dict) -> dict:
    url = _webhook_url()
    if not url:
        logger.warning("[spotlight-slack] SLACK_WEBHOOK_URL not set — skipping reminder.")
        return {"sent": False, "reason": "SLACK_WEBHOOK_URL not configured"}
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(url, json=payload)
            r.raise_for_status()
        return {"sent": True, "status_code": r.status_code}
    except Exception as e:
        logger.exception("[spotlight-slack] post failed")
        return {"sent": False, "error": str(e)}


async def check_and_send_reminders(db, *, lookahead_min: int = 35, lookback_min: int = 25) -> dict:
    """Inspect upcoming spotlight sessions and post a Slack reminder for any
    that start in the [lookback_min, lookahead_min] window AND haven't been
    notified yet (per `spotlight_reminders_sent`).

    Args
    ----
    lookahead_min: send a reminder if session starts ≤ this many minutes from now.
    lookback_min: AND ≥ this many minutes from now (so we don't fire after the
        session has already started or earlier than intended).

    Returns dict with `checked`, `sent`, `skipped` counts for log clarity.
    """
    payload = await spotlight.get_upcoming_spotlight_sessions(db, limit=6)
    sessions = payload.get("sessions") or []
    now = datetime.now(timezone.utc)
    upper = now + timedelta(minutes=lookahead_min)
    lower = now + timedelta(minutes=lookback_min)
    sent = 0
    skipped = 0
    for s in sessions:
        starts_at = s.get("starts_at") or ""
        if not starts_at:
            continue
        try:
            dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if not (lower <= dt <= upper):
            continue
        # Atomic claim: only the first call per session_id wins. Stops a
        # parallel scheduler tick (e.g. old + new dyno during a deploy)
        # from double-sending in the window between find_one + upsert.
        claim = await db.spotlight_reminders_sent.update_one(
            {"session_id": s.get("id")},
            {"$setOnInsert": {
                "session_id": s.get("id"),
                "session_name": s.get("name"),
                "starts_at": starts_at,
                "sent_at": now,
            }},
            upsert=True,
        )
        if claim.upserted_id is None:
            skipped += 1
            continue
        slack_payload = _format_session_blocks(s)
        result = await _post_to_slack(slack_payload)
        if result.get("sent"):
            sent += 1
        else:
            # Send failed — roll back the claim so the next tick can retry.
            await db.spotlight_reminders_sent.delete_one({"session_id": s.get("id")})
            logger.warning(f"[spotlight-slack] failed to send for session {s.get('id')}: {result}")
    return {"checked": len(sessions), "sent": sent, "skipped": skipped}


async def send_session_reminder_now(db, session_id: int) -> dict:
    """Manual trigger: send the reminder for a specific session id (admin
    test). Bypasses the time-window check but still respects idempotency."""
    payload = await spotlight.get_upcoming_spotlight_sessions(db, limit=6)
    for s in payload.get("sessions") or []:
        if s.get("id") == session_id:
            slack_payload = _format_session_blocks(s)
            return await _post_to_slack(slack_payload)
    return {"sent": False, "error": f"session {session_id} not in upcoming list"}
