"""
Slack daily digest for SLA breaches (unanswered Circle posts ≥ 48 h).

Posts to a single Slack incoming webhook URL configured via the
`SLACK_WEBHOOK_URL` environment variable. If the env var is missing/empty,
the digest is a no-op (with a warning log) so the cron never crashes.

Triggered:
  - Daily 08:00 Europe/London via APScheduler (configured in server.py).
  - On-demand via POST /api/notifications/slack/test (admin-only).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

import coach_activity as coach_act

logger = logging.getLogger(__name__)


def _webhook_url() -> Optional[str]:
    url = (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()
    return url or None


async def build_sla_digest_payload(db) -> dict:
    """Compose the Slack message blocks for today's SLA breaches.
    Returns the JSON payload to POST. Never raises."""
    summary = await coach_act.fetch_coach_activity_summary(db)
    sources = []
    for key, label in [
        ("recorded_answers", "Recorded Answer Review"),
        ("interview_support", "Specific Interview Support"),
    ]:
        block = summary.get(key) or {}
        unanswered = block.get("unanswered") or []
        if unanswered:
            sources.append((label, unanswered))

    today = datetime.now(timezone.utc).strftime("%a %d %b")

    if not sources:
        return {
            "text": f"AYCI Coach SLA Digest — {today}: All clear, no posts >48 h unanswered.",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*AYCI Coach SLA Digest — {today}*\n:white_check_mark: All clear — no posts >48 h unanswered.",
                    },
                }
            ],
        }

    total = sum(len(u) for _, u in sources)
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"AYCI Coach SLA Digest — {today}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":rotating_light: *{total} student post"
                    f"{'s' if total != 1 else ''} unanswered for >48 h.*"
                ),
            },
        },
    ]
    for label, items in sources:
        items = sorted(items, key=lambda x: x.get("hours_old", 0), reverse=True)[:8]
        lines = []
        for it in items:
            hrs = it.get("hours_old", 0)
            url = it.get("url") or "#"
            author = it.get("author") or "Unknown"
            name = (it.get("name") or "(untitled)")[:80]
            lines.append(f"• <{url}|{name}> — {author} · {hrs} h")
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{label}* — {len(items)} flagged\n" + "\n".join(lines),
                },
            }
        )
    return {"text": f"AYCI Coach SLA Digest — {total} unanswered posts", "blocks": blocks}


async def send_sla_digest(db) -> dict:
    """Build + POST the digest. Returns a status dict (never raises)."""
    url = _webhook_url()
    if not url:
        logger.warning("[slack] SLACK_WEBHOOK_URL not set — skipping daily digest.")
        return {"sent": False, "reason": "SLACK_WEBHOOK_URL not configured"}
    try:
        payload = await build_sla_digest_payload(db)
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(url, json=payload)
            r.raise_for_status()
        logger.info("[slack] SLA digest sent")
        return {"sent": True, "status_code": r.status_code, "items": payload.get("text")}
    except Exception as e:
        logger.exception("[slack] SLA digest failed")
        return {"sent": False, "error": str(e)}


async def count_unanswered(db) -> int:
    """Return the live count of >48h unanswered posts across both spaces.
    Used by the in-app notification bell badge."""
    try:
        summary = await coach_act.fetch_coach_activity_summary(db)
    except Exception:
        return 0
    total = 0
    for key in ("recorded_answers", "interview_support"):
        block = summary.get(key) or {}
        total += len(block.get("unanswered") or [])
    return total
