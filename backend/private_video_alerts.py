"""
Slack alerts for private-tier videos → the #private-tiers channel.

Two checks, both idempotent (never re-spam) via the `private_video_alerts_sent`
collection:

1. interview_tomorrow — once a day: for any student whose interview is
   tomorrow (per academy_members.interview_date), if they have ANY private
   video on file, post one alert listing those videos. One alert per
   (student, interview_date).

2. unanswered_24h — periodic: any private video submitted >24h ago that is
   NOT marked Done. One alert per video.

"Answered" = status == "done" (per Tessa, 2026-06-05). reply_link alone does
NOT count as answered.

Webhook resolution (so it works without an env redeploy):
   1. app_settings.private_tier_webhook  (DB, set via API)
   2. SLACK_PRIVATE_TIER_WEBHOOK_URL      (env)
   3. SLACK_WEBHOOK_URL                   (env, general fallback — wrong channel)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DASHBOARD_VIDEOS_URL = (
    os.environ.get("PRIVATE_VIDEOS_URL")
    or "https://ayci-dashboard-nfiw.vercel.app/private-videos"
)


# ----------------------------------------------------------------- time helpers
def _today_uk_date():
    # Scheduler runs UK time; +1h from UTC is a good-enough London offset for a
    # date boundary (matches interview_eve_dm's approach).
    return (datetime.now(timezone.utc) + timedelta(hours=1)).date()


def _tomorrow_iso() -> str:
    return (_today_uk_date() + timedelta(days=1)).isoformat()


def _parse_dt(s) -> Optional[datetime]:
    if not s:
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


# ----------------------------------------------------------------- webhook
async def get_webhook_url(db) -> str:
    doc = await db.app_settings.find_one(
        {"id": "private_tier_webhook"}, {"_id": 0, "url": 1}
    )
    db_url = (doc or {}).get("url") or ""
    return (
        db_url.strip()
        or os.environ.get("SLACK_PRIVATE_TIER_WEBHOOK_URL", "").strip()
        or os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    )


async def set_webhook_url(db, url: str) -> dict:
    url = (url or "").strip()
    if url and not url.startswith("https://hooks.slack.com/"):
        return {"ok": False, "error": "Doesn't look like a Slack webhook URL (must start with https://hooks.slack.com/)"}
    await db.app_settings.update_one(
        {"id": "private_tier_webhook"},
        {"$set": {"id": "private_tier_webhook", "url": url}},
        upsert=True,
    )
    return {"ok": True, "url_present": bool(url)}


async def _post(db, text: str) -> bool:
    url = await get_webhook_url(db)
    if not url:
        logger.warning("[pv-alerts] no Slack webhook configured — skipping post")
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(url, json={"text": text})
            if r.status_code >= 300:
                logger.warning(f"[pv-alerts] slack post {r.status_code}: {r.text[:150]}")
                return False
            return True
    except Exception as e:
        logger.warning(f"[pv-alerts] slack post errored: {e}")
        return False


# ----------------------------------------------------------------- dedup
async def _already_sent(db, key: str) -> bool:
    return (await db.private_video_alerts_sent.find_one({"_id": key})) is not None


async def _mark_sent(db, key: str, meta: dict) -> None:
    await db.private_video_alerts_sent.update_one(
        {"_id": key},
        {"$set": {"_id": key, "sent_at": datetime.now(timezone.utc).isoformat(), **meta}},
        upsert=True,
    )


# ----------------------------------------------------------------- helpers
def _is_done(v: dict) -> bool:
    return (v.get("status") or "").strip().lower() == "done"


def _student_name(v: dict) -> str:
    name = f"{(v.get('first_name') or '').strip()} {(v.get('last_name') or '').strip()}".strip()
    return name or (v.get("email") or "Unknown")


async def _videos_for_emails(db, emails: list[str]) -> list[dict]:
    lc = [e.strip().lower() for e in emails if e]
    if not lc:
        return []
    return [v async for v in db.private_video_submissions.find({"email": {"$in": lc}})]


# ----------------------------------------------------------------- check 1
async def check_interview_tomorrow(db, *, dry_run: bool = False) -> dict:
    """Alert for any private video belonging to a student interviewing tomorrow."""
    target = _tomorrow_iso()
    students = [
        s async for s in db.academy_members.find(
            {"interview_date": target},
            {"_id": 1, "email": 1, "circle_email": 1, "name": 1, "tier": 1},
        )
    ]
    posted, candidates = 0, []
    for s in students:
        emails = [e for e in (s.get("email"), s.get("circle_email")) if e]
        vids = await _videos_for_emails(db, emails)
        if not vids:
            continue
        key = f"interview_tomorrow:{(s.get('email') or emails[0]).lower()}:{target}"
        candidate = {"name": s.get("name"), "tier": s.get("tier"), "videos": len(vids), "key": key}
        candidates.append(candidate)
        if dry_run or await _already_sent(db, key):
            continue

        name = s.get("name") or _student_name(vids[0])
        tier = s.get("tier") or "—"
        lines = [
            f"🎬 *Interview tomorrow ({target})* — private video(s) to review",
            f"*{name}* ({tier})",
        ]
        for v in vids:
            status = (v.get("status") or "new").title()
            url = v.get("tally_video_url") or ""
            num = v.get("submission_number") or "?"
            lines.append(f"   • #{num} — {status}" + (f" — <{url}|video>" if url else ""))
        lines.append(f"<{DASHBOARD_VIDEOS_URL}|Open Private-Tier Videos>")

        if await _post(db, "\n".join(lines)):
            await _mark_sent(db, key, {"type": "interview_tomorrow",
                                       "email": (s.get("email") or "").lower(),
                                       "interview_date": target})
            posted += 1
    return {"target": target, "students_tomorrow": len(students),
            "with_videos": len(candidates), "alerts_posted": posted,
            "candidates": candidates if dry_run else None}


# ----------------------------------------------------------------- check 2
async def check_unanswered_24h(db, *, dry_run: bool = False) -> dict:
    """Alert for any private video submitted >24h ago that isn't marked Done."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    posted, overdue = 0, []
    async for v in db.private_video_submissions.find({}):
        if _is_done(v):
            continue
        dt = _parse_dt(v.get("submitted_at") or v.get("created_at"))
        if not dt or dt > cutoff:
            continue
        vid = str(v.get("_id"))
        hours = int((datetime.now(timezone.utc) - dt).total_seconds() // 3600)
        key = f"unanswered_24h:{vid}"
        overdue.append({"name": _student_name(v), "hours": hours,
                        "status": v.get("status"), "key": key})
        if dry_run or await _already_sent(db, key):
            continue

        name = _student_name(v)
        status = (v.get("status") or "new").title()
        url = v.get("tally_video_url") or ""
        text = (
            f"⏰ *Private video unanswered for {hours}h* (not marked Done)\n"
            f"*{name}* — status {status}" + (f" — <{url}|video>" if url else "") + "\n"
            f"<{DASHBOARD_VIDEOS_URL}|Open Private-Tier Videos>"
        )
        if await _post(db, text):
            await _mark_sent(db, key, {"type": "unanswered_24h",
                                       "email": (v.get("email") or "").lower(),
                                       "video_id": vid})
            posted += 1
    return {"overdue_not_done": len(overdue), "alerts_posted": posted,
            "candidates": overdue if dry_run else None}
