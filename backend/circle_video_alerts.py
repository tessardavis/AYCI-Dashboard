"""
Slack alert: when a student posts > 3 videos in the "Recorded Answer Review"
Circle space within a single calendar week (Mon 00:00 → Sun 23:59 UK), ping
`#circle-days` once per (member, week). Idempotent — re-running never spams.

Scheduled every 5 min from `server.py`. The cross-the-threshold detection is
"first time we observe count > 3 for a given (name, week_start)".
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx

import coach_activity as coach_act

logger = logging.getLogger(__name__)


def _webhook_url_env() -> str:
    """Channel-specific webhook for #circle-days. Falls back to the general
    `SLACK_WEBHOOK_URL` so the feature still works (in a wrong channel)
    until the team creates the dedicated webhook."""
    return (
        os.environ.get("SLACK_CIRCLE_DAYS_WEBHOOK_URL")
        or os.environ.get("SLACK_WEBHOOK_URL")
        or ""
    ).strip()


async def get_webhook_url(db) -> str:
    """Read the configured webhook URL. Order of preference:
       1. `app_settings.circle_days_webhook` (DB-stored, set via API)
       2. env var `SLACK_CIRCLE_DAYS_WEBHOOK_URL`
       3. env var `SLACK_WEBHOOK_URL` (general fallback — wrong channel)
    Storing the URL in the DB lets non-technical admins set it without an
    Emergent redeploy when new env-var slots can't be added."""
    doc = await db.app_settings.find_one(
        {"id": "circle_days_webhook"}, {"_id": 0, "url": 1}
    )
    db_url = (doc or {}).get("url") or ""
    return (db_url.strip() or _webhook_url_env())


async def set_webhook_url(db, url: str) -> dict:
    url = (url or "").strip()
    if url and not url.startswith("https://hooks.slack.com/"):
        return {"ok": False, "error": "Doesn't look like a Slack webhook URL (must start with https://hooks.slack.com/)"}
    await db.app_settings.update_one(
        {"id": "circle_days_webhook"},
        {"$set": {"id": "circle_days_webhook", "url": url}},
        upsert=True,
    )
    return {"ok": True, "url_present": bool(url)}


async def _post(db, text: str) -> dict:
    url = await get_webhook_url(db)
    if not url:
        return {"sent": False, "reason": "no webhook configured"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(url, json={"text": text})
            r.raise_for_status()
        return {"sent": True, "status_code": r.status_code}
    except Exception as e:
        logger.exception("[circle-video-alerts] post failed")
        return {"sent": False, "error": str(e)}


async def check_and_send(db) -> dict:
    """Inspect the Recorded Answer Review space, find any student who has
    posted more than 3 videos in the current calendar week, and post a Slack
    line — once per (member, week_start). User-dismissed alerts (via the
    Coach Activity UI) are also suppressed so the team can manually silence
    a flag without waiting for the next week."""
    try:
        result = await coach_act.analyse_circle_space(
            coach_act.RECORDED_ANSWER_SPACE_ID,
            coach_act.RECORDED_ANSWERS_START,
            "Recorded Answer Review",
            db=db,
        )
    except Exception as e:
        logger.warning(f"[circle-video-alerts] analyse failed: {e}")
        return {"sent": 0, "error": str(e)}

    rate_limited = result.get("rate_limited") or []
    sent = 0
    skipped = 0
    # Pull the user-dismissed keys so we never re-ping after a dismiss.
    from coach_activity_dismissals import list_dismissed_keys, rate_limit_key
    dismissed = await list_dismissed_keys(db, "rate_limited")
    for item in rate_limited:
        name = (item.get("name") or "").strip()
        week_start = (item.get("week_start") or "").strip()
        count = int(item.get("count") or 0)
        if not name or not week_start or count <= coach_act.WEEKLY_VIDEO_LIMIT:
            continue
        # Use the SAME dedup key the dismissal store uses, so a manual
        # dismiss permanently silences future pings AND so we're robust to
        # whitespace/case drift between Circle API responses.
        key = rate_limit_key(name, week_start)
        if key in dismissed:
            skipped += 1
            continue
        # Atomic claim: only the first call per (member, week) wins. Stops
        # parallel scheduler ticks (e.g. old + new dyno during a deploy)
        # from double-sending in the window between find_one + insert_one.
        claim = await db.circle_video_alerts_sent.update_one(
            {"_id": key},
            {"$setOnInsert": {
                "_id": key,
                "name": name,
                "week_start": week_start,
                "count_at_alert": count,
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        if claim.upserted_id is None:
            skipped += 1
            continue
        text = f"🎬 *{name}* posted *{count} videos* this week (week of {week_start}) in Recorded Answer Review."
        post_result = await _post(db, text)
        if post_result.get("sent"):
            sent += 1
            logger.info(f"[circle-video-alerts] sent for {name} ({count}/wk, week {week_start})")
        else:
            # Send failed — roll back the claim so the next tick can retry.
            await db.circle_video_alerts_sent.delete_one({"_id": key})
            logger.warning(f"[circle-video-alerts] failed to post for {name}: {post_result}")

    return {"sent": sent, "skipped": skipped, "candidates": len(rate_limited)}
