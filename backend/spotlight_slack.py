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

import httpx

import spotlight

logger = logging.getLogger(__name__)


def _webhook_url() -> Optional[str]:
    url = (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()
    return url or None


def _format_session_blocks(session: dict) -> dict:
    """Build the Slack block payload for a single session."""
    name = session.get("name") or "Spotlight session"
    starts_at = session.get("starts_at") or ""
    try:
        dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        when = dt.strftime("%a %d %b · %H:%M UTC")
    except ValueError:
        when = starts_at[:16]

    students = session.get("students") or []
    eligible = [s for s in students if s.get("eligible")]
    header = (
        f"*🎯 Spotlight prep · {name}*\n"
        f"_Starts in ~30 min ({when})_\n"
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

    actions = []
    if session.get("circle_url"):
        actions.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"<{session['circle_url']}|Open this session in Circle>"},
        })

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
        # Idempotency: have we already sent this reminder?
        sent_doc = await db.spotlight_reminders_sent.find_one({"session_id": s.get("id")})
        if sent_doc:
            skipped += 1
            continue
        slack_payload = _format_session_blocks(s)
        result = await _post_to_slack(slack_payload)
        if result.get("sent"):
            await db.spotlight_reminders_sent.update_one(
                {"session_id": s.get("id")},
                {"$set": {
                    "session_id": s.get("id"),
                    "session_name": s.get("name"),
                    "starts_at": starts_at,
                    "sent_at": now,
                }},
                upsert=True,
            )
            sent += 1
        else:
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
