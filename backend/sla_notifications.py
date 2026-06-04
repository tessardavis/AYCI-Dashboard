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
from datetime import datetime, timezone, date
from typing import Optional

import httpx

import coach_activity as coach_act

logger = logging.getLogger(__name__)


def _webhook_url() -> Optional[str]:
    url = (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()
    return url or None


async def _is_cohort_active(db, today: Optional[date] = None) -> bool:
    """Decide whether the digest should run today.

    Cohort is "active" if today is on or before the latest configured cohort
    end date. If neither end date is set, fall back to legacy behaviour
    (always active) so existing installs keep working until end dates are
    filled in via the Settings → Coach Spaces UI.
    """
    today = today or datetime.now(timezone.utc).date()
    try:
        import settings_store
        cfg = await settings_store.get_coach_spaces(db)
    except Exception:
        return True  # fail open — never silently kill the digest on a settings read error
    ends: list[date] = []
    for key in ("recorded_answer_end", "interview_support_end"):
        v = cfg.get(key)
        if not v:
            continue
        try:
            ends.append(date.fromisoformat(v))
        except (TypeError, ValueError):
            continue
    if not ends:
        return True  # no end dates set yet — legacy behaviour
    # If today is after BOTH end dates, the cohort is over. If at least one
    # space is still inside its window, keep firing.
    return today <= max(ends)


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


async def send_sla_digest(db, *, force: bool = False) -> dict:
    """Build + POST the digest. Returns a status dict (never raises).

    Atomic daily-claim guard: only the first call per UTC day actually
    posts; subsequent calls (cron re-fire, parallel container during a
    deploy, accidental manual trigger) see the claim and no-op. Pass
    `force=True` to bypass the claim (used by the admin /test endpoint).
    """
    url = _webhook_url()
    if not url:
        logger.warning("[slack] SLACK_WEBHOOK_URL not set — skipping daily digest.")
        return {"sent": False, "reason": "SLACK_WEBHOOK_URL not configured"}

    # Outside the cohort window? Don't fire — was producing daily "All clear"
    # noise in #coaching-spotlight between cohorts. Admin sets / clears the
    # end date in Settings → Coach Spaces. `force=True` (admin test) still
    # sends so we can verify Slack wiring out-of-cohort.
    if not force and not await _is_cohort_active(db):
        logger.info("[slack] SLA digest skipped — outside cohort window")
        return {"sent": False, "reason": "outside_cohort_window"}

    today_key = f"sla_digest:{datetime.now(timezone.utc).date().isoformat()}"
    if not force:
        claim = await db.scheduler_claims.update_one(
            {"_id": today_key},
            {"$setOnInsert": {"_id": today_key,
                              "claimed_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        if claim.upserted_id is None:
            logger.info(f"[slack] SLA digest already sent today ({today_key}) — skipping")
            return {"sent": False, "reason": "already_sent_today", "claim_key": today_key}

    try:
        payload = await build_sla_digest_payload(db)
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(url, json=payload)
            r.raise_for_status()
        logger.info("[slack] SLA digest sent")
        return {"sent": True, "status_code": r.status_code, "items": payload.get("text")}
    except Exception as e:
        # Roll back the claim so a manual retry or the next cron can try again.
        if not force:
            try:
                await db.scheduler_claims.delete_one({"_id": today_key})
            except Exception:
                pass
        logger.exception("[slack] SLA digest failed")
        return {"sent": False, "error": str(e)}


async def count_unanswered(db) -> int:
    """Return the live count of >48h unanswered posts across both spaces.
    Used by the in-app notification bell badge and the Pulse Score.

    Uses the same 30-min SWR cache as the Coach Activity dashboard so this is
    sub-100 ms on the hot path; otherwise it would trigger a ~10s Circle sweep
    on every dashboard load (including login → WeeklyScorecard landing)."""
    try:
        import launches as launches_mod
        summary = await launches_mod._stale_while_revalidate(
            db,
            "coach_activity:summary",
            ttl_min=30,
            compute_fn=lambda: coach_act.fetch_coach_activity_summary(db),
        )
    except Exception:
        return 0
    total = 0
    for key in ("recorded_answers", "interview_support"):
        block = summary.get(key) or {}
        total += len(block.get("unanswered") or [])
    return total
