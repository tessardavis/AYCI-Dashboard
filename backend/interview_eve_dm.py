"""
Interview-Eve DM check-in.

Every weekday at 19:00 UK time, sends a Circle DM as Coralie to every
student whose interview is the next day (per the Monday Academy Members
board), asking:

    "Hi {first}, how supported do you feel heading into your interview
     tomorrow? Reply with a number from 1-10."

Students reply with a number (e.g. "7"). The existing polling bot
recognises the reply (`circle_dm_poll`), parses the score, saves it on
the `interview_eve_dms` record, and if the score is ≤5 fires a Slack
alert — to the private-tier channel for private-tier students, or to the
coach-chat channel for everyone else.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

import circle_api
import upcoming_interviews

logger = logging.getLogger(__name__)

COACH_EMAIL = (
    os.environ.get("INTERVIEW_EVE_COACH_EMAIL")
    or "coralie.fairon@yahoo.co.uk"
)
COACH_DISPLAY_NAME = os.environ.get("INTERVIEW_EVE_COACH_NAME") or "Coralie"
SCORE_LOW_THRESHOLD = int(os.environ.get("INTERVIEW_EVE_SCORE_THRESHOLD") or 5)

# Two webhooks for the two routing groups
SLACK_PRIVATE_TIER_WEBHOOK = os.environ.get("SLACK_PRIVATE_TIER_WEBHOOK_URL", "")
SLACK_COACH_CHAT_WEBHOOK = os.environ.get("SLACK_COACH_CHAT_WEBHOOK_URL", "")
SLACK_FALLBACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "")


def _today_uk() -> datetime.date:
    """Today's date in Europe/London. APScheduler already fires us at 19:00
    UK, so "tomorrow" from this fn's perspective IS the interview day."""
    return (datetime.now(timezone.utc) + timedelta(hours=1)).date()


def _tomorrow_iso() -> str:
    return (_today_uk() + timedelta(days=1)).isoformat()


def _build_dm_body(first_name: str) -> str:
    coach_first = (COACH_DISPLAY_NAME or "").split(" ")[0] or "the team"
    return (
        f"Hi {first_name}! 💪 Hope you're feeling good about tomorrow's interview. "
        f"Quick check-in: on a scale of 1 to 10, how supported do you feel heading in? "
        f"Just pop a number back and if anything's not quite right we'll be in touch "
        f"tonight to help.\n\n"
        f"You've got this!\n{coach_first}"
    )


def _is_private_tier(student: dict) -> bool:
    """Anything that isn't a pure Academy/Silver/Gold student is private tier
    in the routing sense."""
    tier = (student.get("tier") or "").strip().lower()
    if not tier:
        return False
    parts = [p.strip() for p in tier.split(",") if p.strip()]
    academy_equiv = {"academy", "silver", "gold"}
    return any(p not in academy_equiv for p in parts)


async def _find_circle_member_by_email(db, email: str) -> Optional[dict]:
    """Lookup a Circle community member by email from the cache."""
    if not email:
        return None
    e = email.strip().lower()
    doc = await db.circle_members_cache.find_one({"_id": "all"}, {"_id": 0})
    for m in (doc or {}).get("members") or []:
        if (m.get("email") or "").strip().lower() == e:
            return m
    return None


async def _ensure_dm_chat_room(admin_email: str, member_id: int) -> Optional[str]:
    """Get-or-create the 1:1 DM chat room between `admin_email` (the coach)
    and the target community member. Returns the chat_room_uuid or None.

    Circle's Headless API exposes a find-or-create endpoint at
    `POST /api/headless/v1/messages` which returns the existing or new chat
    room for a pair of community members. Posting body shape:
        { "community_member_ids": [<member_id>] }
    The caller's own `community_member_id` is implicit (derived from the
    Bearer access token).
    """
    # We need the coach's access token to create the room as them.
    from db import db as _db
    access_token = await circle_api._get_access_token(_db, admin_email)
    if not access_token:
        return None
    async with httpx.AsyncClient(timeout=20) as c:
        try:
            r = await c.post(
                f"{circle_api.HEADLESS_BASE}/messages",
                headers={"Authorization": f"Bearer {access_token}",
                         "Content-Type": "application/json"},
                json={"chat_room": {
                    "kind": "direct",
                    "community_member_ids": [int(member_id)],
                }},
            )
            if r.status_code in (200, 201):
                body = r.json()
                # Response shape: {"chat_room_uuid": "...", "chat_room": {...}, ...}
                return (
                    body.get("chat_room_uuid")
                    or (body.get("chat_room") or {}).get("uuid")
                    or body.get("uuid")
                )
            logger.warning(f"[interview-eve] create chat_room failed {r.status_code} {r.text[:200]}")
        except Exception as e:
            logger.warning(f"[interview-eve] create chat_room errored: {e}")
    return None


async def send_interview_eve_dms(db) -> dict:
    """Main job. Returns a summary dict for logging / observability."""
    target_date = _tomorrow_iso()
    summary = {
        "target_date": target_date,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "sent": 0, "skipped": 0, "errors": [], "details": [],
    }

    # All upcoming interviews in the next ~3 days, then filter to exactly tomorrow.
    payload = await upcoming_interviews.fetch_upcoming_interviews(db=db, days=3)
    candidates = []
    for group_key in ("academy", "private"):
        for s in payload.get(group_key) or []:
            if s.get("interview_date") == target_date:
                candidates.append(s)
    summary["candidates"] = len(candidates)

    for student in candidates:
        email = (student.get("email") or "").strip().lower()
        if not email:
            summary["skipped"] += 1
            summary["details"].append({"name": student.get("name"), "skip": "no_email"})
            continue

        # Atomic claim: try to insert a placeholder row for this
        # (student, date) pair. If we created it (upserted_id is set) we
        # own the slot and proceed. If a parallel invocation got there
        # first, upserted_id is None and we skip - prevents duplicate
        # DMs when the cron double-fires (e.g. container restart near
        # 19:00 racing with the scheduled fire).
        rec_id = f"eve:{target_date}:{email}"
        claim = await db.interview_eve_dms.update_one(
            {"id": rec_id},
            {"$setOnInsert": {
                "id": rec_id,
                "student_email": email,
                "interview_date": target_date,
                "claimed_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        if claim.upserted_id is None:
            summary["skipped"] += 1
            summary["details"].append({"name": student.get("name"), "skip": "already_sent"})
            continue

        # Helper: roll back the placeholder claim if anything below fails
        # so the next scheduled run can retry this student. Without this,
        # a transient failure (e.g. no chat room) would permanently lock
        # them out for this interview_date.
        async def _release_claim():
            await db.interview_eve_dms.delete_one({"id": rec_id})

        member = await _find_circle_member_by_email(db, email)
        if not member:
            await _release_claim()
            summary["skipped"] += 1
            summary["details"].append({"name": student.get("name"), "skip": "no_circle_member"})
            continue
        member_id = member.get("id")
        if not member_id:
            await _release_claim()
            summary["skipped"] += 1
            continue

        first_name = (student.get("name") or "").split(" ")[0] or "there"
        body = _build_dm_body(first_name)

        room_uuid = await _ensure_dm_chat_room(COACH_EMAIL, member_id)
        if not room_uuid:
            await _release_claim()
            summary["errors"].append(f"{email}: no chat room")
            continue

        posted = await circle_api.post_dm_message(db, COACH_EMAIL, room_uuid, body)
        if posted is None:
            await _release_claim()
            summary["errors"].append(f"{email}: post failed")
            continue

        # Save a record so the polling bot can recognise replies on this thread.
        rec = {
            "id": f"eve:{target_date}:{email}",
            "student_email": email,
            "student_name": student.get("name"),
            "interview_date": target_date,
            "tier": student.get("tier"),
            "is_private_tier": _is_private_tier(student),
            "circle_member_id": int(member_id),
            "thread_uuid": room_uuid,
            "coach_admin_email": COACH_EMAIL,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "sent_body": body,
            "score": None,
            "score_received_at": None,
        }
        await db.interview_eve_dms.update_one(
            {"id": rec["id"]}, {"$set": rec}, upsert=True,
        )

        # Mark the thread state in circle_dm_threads so the polling bot
        # treats our outbound DM as bot-sent (not a human takeover) and
        # also knows to listen for an interview-eve score on the next
        # student message in this thread.
        sent_bodies = [body]
        await db.circle_dm_threads.update_one(
            {"id": f"thread:{room_uuid}"},
            {"$set": {
                "id": f"thread:{room_uuid}",
                "thread_uuid": room_uuid,
                "coach_admin_email": COACH_EMAIL,
                "student_member_id": int(member_id),
                "student_name": student.get("name"),
                "state": "active",
                "interview_eve_record_id": rec["id"],
                "sent_bodies": sent_bodies,
                "last_seen_message_id": 0,
                "last_activity_at": rec["sent_at"],
                "last_reply_text": body,
                "last_reply_at": rec["sent_at"],
            }},
            upsert=True,
        )
        summary["sent"] += 1
        summary["details"].append({"name": student.get("name"), "sent": True, "thread_uuid": room_uuid})

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(f"[interview-eve] {summary['sent']} sent, {summary['skipped']} skipped, errors={summary['errors']}")
    return summary


# ---------------------------------------------------------------- Score parsing
_SCORE_RE = re.compile(r"\b(10|[1-9])\b")


def parse_score(text: str) -> Optional[int]:
    """Extract a 1-10 score from a student's freeform reply. Returns the
    first standalone 1-10 number, or None. Examples that should match:
      "7"           → 7
      "i'd say 4"   → 4
      "maybe 8 today" → 8
      "⁹"          → 9    (Unicode superscript — auto-normalised)
      "9️⃣"          → 9    (keycap emoji — auto-normalised)
    Multi-digit numbers (e.g. "11am") don't match because we require word
    boundaries around the 1-10 digit. Long replies (>30 chars) only count
    if they contain a rating-like keyword.

    Unicode handling: Circle's keyboard/emoji shortcuts let students reply
    with superscripts (⁹), keycap emoji (9️⃣), full-width digits (９), etc.
    We NFKC-normalise the text before matching so all variants collapse
    to plain ASCII digits.
    """
    if not text:
        return None
    import unicodedata
    # NFKC turns superscripts/subscripts/full-width digits into ASCII.
    # Keycap emoji (e.g. "9️⃣") survive NFKC, so strip the trailing variation
    # selector + combining-enclosing-keycap separately.
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("\u20e3", "").replace("\ufe0f", "")
    t = t.strip()
    low = t.lower()
    m = _SCORE_RE.search(t)
    if not m:
        return None
    n = int(m.group(1))
    if n < 1 or n > 10:
        return None
    # Short replies: very likely a score. Long replies: only treat as a
    # score if a rating-like keyword is present.
    if len(t) <= 30:
        return n
    rating_hints = ("/10", "out of 10", "rate", "score", "supported", "feeling")
    if any(h in low for h in rating_hints):
        return n
    return None


async def maybe_record_score(db, thread_uuid: str, student_text: str) -> Optional[dict]:
    """Called by the polling bot when it sees a new student message.

    If the thread has an `interview_eve_record_id` AND the message parses as
    a 1-10 score AND we haven't already recorded a score, save it and (if
    low) fire the Slack notification. Returns the updated record or None.
    """
    thread_state = await db.circle_dm_threads.find_one(
        {"thread_uuid": thread_uuid}, {"_id": 0, "interview_eve_record_id": 1},
    )
    if not thread_state:
        return None
    rec_id = thread_state.get("interview_eve_record_id")
    if not rec_id:
        return None
    rec = await db.interview_eve_dms.find_one({"id": rec_id}, {"_id": 0})
    if not rec or rec.get("score") is not None:
        return None
    score = parse_score(student_text)
    if score is None:
        return None
    now = datetime.now(timezone.utc).isoformat()
    res = await db.interview_eve_dms.update_one(
        {"id": rec_id},
        {"$set": {
            "score": score,
            "score_received_at": now,
            "score_raw_text": student_text[:200],
        }},
    )
    logger.info(
        f"[interview-eve] score-write rec_id={rec_id} score={score} "
        f"matched={res.matched_count} modified={res.modified_count}"
    )
    rec["score"] = score
    rec["score_received_at"] = now
    rec["score_raw_text"] = student_text[:200]

    if score <= SCORE_LOW_THRESHOLD:
        await _slack_alert_low_score(rec, score)
    return rec


async def _slack_alert_low_score(rec: dict, score: int) -> None:
    """Post a Slack alert for a low interview-eve confidence score."""
    is_private = rec.get("is_private_tier")
    url = (
        (SLACK_PRIVATE_TIER_WEBHOOK if is_private else SLACK_COACH_CHAT_WEBHOOK)
        or SLACK_FALLBACK_WEBHOOK
    )
    if not url:
        logger.warning("[interview-eve] no Slack webhook configured, skipping low-score alert")
        return
    name = rec.get("student_name") or rec.get("student_email") or "Unknown"
    tier = rec.get("tier") or "Academy"
    msg = (
        f":warning: *Low interview-eve confidence: {score}/10* "
        f"({'Private Tier' if is_private else 'Academy'})\n"
        f"• Student: *{name}* ({tier})\n"
        f"• Interview: tomorrow ({rec.get('interview_date')})\n"
        f"• They replied: _{(rec.get('score_raw_text') or '')[:120]}_"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(url, json={"text": msg})
            if r.status_code >= 300:
                logger.warning(f"[interview-eve] slack post failed: {r.status_code} {r.text[:120]}")
    except Exception as e:
        logger.warning(f"[interview-eve] slack post errored: {e}")
