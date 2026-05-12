"""
Polling-based Circle DM bot — v2 of the Circle community AI auto-responder.

Replaces the Circle Workflow webhook approach (which only fires once per
member, by Circle's design). This module polls the Headless API for each
coach admin every minute, watches for new student DMs, and replies in-thread
using the existing playbook + LLM logic from `circle_dm_bot`.

Behaviour:
  • For each enabled coach admin, list their DM threads
  • For each thread, determine new student messages since `last_seen_message_id`
  • If a coach posted manually (a message NOT in our `sent_message_ids`),
    mark the thread `human_takeover` and back off permanently
  • Otherwise:
      – escalation_phrase ("create a ticket", "talk to human"…)  → escalate
      – sensitive keyword                                        → escalate + Slack
      – playbook covers it                                       → AI reply
      – playbook doesn't cover it                                → escalate
  • All replies include the AI disclosure
  • On first sight of a thread we DON'T reply — we just record the last id,
    so we don't auto-reply to a backlog of old messages on the first run
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import circle_api
import circle_dm_bot

logger = logging.getLogger(__name__)

# How many old messages we initially seed on first-sight of a thread. We
# *record* the most recent N as already-seen so the bot doesn't reply to
# historical chatter when polling first turns on for an existing thread.
INITIAL_SEED_LIMIT = 20

# Hard daily cap on AI replies per thread to prevent runaway loops.
DAILY_REPLY_CAP_PER_THREAD = 8

# Phrases that signal the student wants a human / a ticket. Always escalates
# regardless of playbook coverage.
ESCALATION_PHRASES = {
    "talk to a human", "talk to human", "speak to human", "speak to a human",
    "talk to a person", "talk to someone", "speak to someone",
    "create a ticket", "open a ticket", "submit a ticket", "support ticket",
    "raise a ticket", "log a ticket", "real person", "human help",
    "stop bot", "stop the bot", "real human",
}


def _settings_id() -> str:
    return "circle_dm_bot_config"


async def get_config(db) -> dict:
    """Read the bot config doc. Returns sensible defaults if not set."""
    doc = await db.app_settings.find_one(
        {"id": _settings_id()}, {"_id": 0},
    ) or {}
    return {
        "enabled": doc.get("enabled", True),
        "coach_emails": doc.get("coach_emails") or [
            os.environ.get("CIRCLE_BOT_DEFAULT_COACH_EMAIL")
            or "tessa@medicalinterviewprep.com",
        ],
        "excluded_member_tags": doc.get("excluded_member_tags") or [
            "Circle Member", "Autoreply hold", "Interview week", "AYGI 25/26",
        ],
        "tag_exclusion_coach_emails": doc.get("tag_exclusion_coach_emails") or [
            "tessa@medicalinterviewprep.com",
        ],
        "last_poll_at": doc.get("last_poll_at"),
        "last_poll_summary": doc.get("last_poll_summary") or {},
    }


async def set_config(db, *, enabled: Optional[bool] = None,
                     coach_emails: Optional[list[str]] = None,
                     excluded_member_tags: Optional[list[str]] = None,
                     tag_exclusion_coach_emails: Optional[list[str]] = None) -> dict:
    update = {}
    if enabled is not None:
        update["enabled"] = bool(enabled)
    if coach_emails is not None:
        update["coach_emails"] = [e.strip().lower() for e in coach_emails if e.strip()]
    if excluded_member_tags is not None:
        update["excluded_member_tags"] = [t.strip() for t in excluded_member_tags if t.strip()]
    if tag_exclusion_coach_emails is not None:
        update["tag_exclusion_coach_emails"] = [e.strip().lower() for e in tag_exclusion_coach_emails if e.strip()]
    if update:
        update["id"] = _settings_id()
        await db.app_settings.update_one(
            {"id": _settings_id()},
            {"$set": update}, upsert=True,
        )
    return await get_config(db)


def _msg_body(m: dict) -> str:
    """Extract human-readable text from a Circle message record."""
    return (
        m.get("body")
        or m.get("plain_text")
        or (m.get("rich_text_body") or {}).get("circle_ios_fallback_text")
        or m.get("text")
        or ""
    ).strip()


def _msg_sender_id(m: dict) -> Optional[int]:
    s = m.get("sender") or {}
    sid = s.get("community_member_id") or s.get("id") or m.get("community_member_id")
    try:
        return int(sid) if sid is not None else None
    except (ValueError, TypeError):
        return None


def _msg_id(m: dict) -> Optional[int]:
    mid = m.get("id") or m.get("message_id")
    try:
        return int(mid) if mid is not None else None
    except (ValueError, TypeError):
        return None


def _wants_escalation(text: str) -> bool:
    low = (text or "").lower()
    return any(p in low for p in ESCALATION_PHRASES)


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


async def _get_thread_state(db, thread_uuid: str) -> Optional[dict]:
    return await db.circle_dm_threads.find_one(
        {"id": f"thread:{thread_uuid}"}, {"_id": 0},
    )


async def _save_thread_state(db, thread_uuid: str, patch: dict) -> None:
    patch = {**patch, "id": f"thread:{thread_uuid}", "thread_uuid": thread_uuid}
    await db.circle_dm_threads.update_one(
        {"id": f"thread:{thread_uuid}"},
        {"$set": patch},
        upsert=True,
    )


def _identify_student(thread: dict, admin_member_id: int) -> tuple[Optional[int], Optional[str]]:
    """Return (student_member_id, student_name) — the non-admin participant.

    Our normalised thread shape (from circle_api.list_dm_threads) puts the
    other-side participants at `other_participants_preview`. Falls back to
    the `last_message.sender` if the participant list is empty.
    """
    for p in thread.get("other_participants_preview") or []:
        pid = p.get("community_member_id") or p.get("id")
        try:
            if pid and int(pid) != admin_member_id:
                name = (
                    p.get("name")
                    or " ".join(filter(None, [p.get("first_name"), p.get("last_name")])).strip()
                    or "there"
                )
                return int(pid), name
        except (ValueError, TypeError):
            continue
    s = (thread.get("last_message") or {}).get("sender") or {}
    pid = s.get("community_member_id") or s.get("id")
    try:
        if pid and int(pid) != admin_member_id:
            return int(pid), s.get("name") or "there"
    except (ValueError, TypeError):
        pass
    return None, None


def _ai_disclosure(student_first: str, coach_name: str) -> str:
    return f"Hi {student_first}, this is an auto-response from {coach_name}'s account."


def _holding_handoff(student_first: str, coach_name: str) -> str:
    return (
        f"{_ai_disclosure(student_first, coach_name)} "
        "I'm passing this to the team, they'll be in touch within 24h.\nBest, AYCI Team"
    )


# --------------------------------------------------------- Per-thread processor
async def _process_thread(
    db, *, admin_email: str, admin_member_id: int, coach_name: str,
    thread: dict, excluded_tags_lower: set[str],
) -> dict:
    """Returns a small dict for the poll summary."""
    chat_room_uuid = thread.get("chat_room_uuid")
    if not chat_room_uuid:
        return {"skipped": "no_uuid"}

    student_id, student_name = _identify_student(thread, admin_member_id)
    if not student_id:
        return {"skipped": "no_student"}

    state = await _get_thread_state(db, chat_room_uuid)

    # Already escalated / human took over / tag-excluded — silent.
    if state and state.get("state") in ("escalated", "human_takeover", "tag_excluded"):
        return {"skipped": state["state"]}

    # Fast-path: skip threads with no new messages.
    # The inline `last_message` is the most recent message in the room. If
    # its id <= last_seen, nothing to do — avoids 1 API call per thread on
    # quiet polls (we have ~400 threads, so this is a big saving).
    inline_last = thread.get("last_message") or {}
    inline_last_id = _msg_id(inline_last)
    last_seen = (state or {}).get("last_seen_message_id") or 0
    if state and inline_last_id is not None and inline_last_id <= last_seen:
        return {"skipped": "no_new"}

    # First-sight seeding fast-path: use the inline `last_message` to record
    # last_seen without fetching the full message list (avoids 1 API call
    # per thread on the very first poll across all of Tessa's ~400 rooms).
    if not state:
        await _save_thread_state(db, chat_room_uuid, {
            "coach_admin_email": admin_email,
            "student_member_id": student_id,
            "student_name": student_name,
            "state": "active",
            "last_seen_message_id": inline_last_id or 0,
            "sent_message_ids": [],
            "ai_reply_count_today": 0,
            "ai_reply_count_date": _today_str(),
            "first_seen_at": datetime.now(timezone.utc).isoformat(),
            "last_activity_at": datetime.now(timezone.utc).isoformat(),
        })
        return {"seeded": chat_room_uuid}

    messages = await circle_api.list_thread_messages_for_admin(
        db, admin_email, chat_room_uuid, per_page=20,
    )
    if not messages:
        return {"skipped": "no_messages"}

    # Sort oldest -> newest. Circle returns newest-first by default.
    messages.sort(key=lambda m: m.get("created_at") or "")
    latest_id = _msg_id(messages[-1])
    new_messages = [
        m for m in messages
        if _msg_id(m) is not None and _msg_id(m) > last_seen
    ]
    if not new_messages:
        return {"skipped": "no_new"}
    sent_ids = set(state.get("sent_message_ids") or [])
    sent_bodies = set(state.get("sent_bodies") or [])

    # Detect human takeover: any admin-authored message that's NOT one of
    # the bot's recent replies (matched by message id OR by body text —
    # Circle's chat POST returns 202 without the new message id, so we also
    # remember the bodies we've posted recently to dedupe robustly).
    for m in new_messages:
        sid = _msg_sender_id(m)
        mid = _msg_id(m)
        body = _msg_body(m)
        if sid == admin_member_id and mid not in sent_ids and body not in sent_bodies:
            await _save_thread_state(db, chat_room_uuid, {
                "state": "human_takeover",
                "last_seen_message_id": latest_id,
                "last_activity_at": datetime.now(timezone.utc).isoformat(),
                "human_takeover_at": datetime.now(timezone.utc).isoformat(),
            })
            return {"human_takeover": chat_room_uuid}

    # Find the latest STUDENT message (sid != admin & sid == student_id)
    latest_student_msg = None
    for m in reversed(new_messages):
        sid = _msg_sender_id(m)
        if sid == student_id:
            latest_student_msg = m
            break
    if not latest_student_msg:
        # All new messages were the bot's own — nothing to react to.
        await _save_thread_state(db, chat_room_uuid, {
            "last_seen_message_id": latest_id,
            "last_activity_at": datetime.now(timezone.utc).isoformat(),
        })
        return {"skipped": "no_student_msg"}

    student_text = _msg_body(latest_student_msg)
    if not student_text:
        await _save_thread_state(db, chat_room_uuid, {
            "last_seen_message_id": latest_id,
        })
        return {"skipped": "empty_body"}

    # ---- Tag exclusion check ---------------------------------------------
    # If the student carries any excluded member tag (e.g. "Interview week",
    # "Autoreply hold"), the bot stays completely silent — no reply, no
    # ticket, no Slack. The coach handles it themselves in Circle.
    if excluded_tags_lower:
        member = await circle_api.fetch_member_cached(db, student_id)
        student_tags = [(t or "").lower() for t in (member or {}).get("tags") or []]
        matched = [t for t in student_tags if t in excluded_tags_lower]
        if matched:
            await _save_thread_state(db, chat_room_uuid, {
                "state": "tag_excluded",
                "last_seen_message_id": latest_id,
                "matched_excluded_tags": matched,
                "last_activity_at": datetime.now(timezone.utc).isoformat(),
            })
            return {"tag_excluded": chat_room_uuid, "tags": matched}

    first = (student_name or "there").split(" ")[0]
    today = _today_str()
    reply_count_today = (
        state.get("ai_reply_count_today", 0)
        if state.get("ai_reply_count_date") == today else 0
    )
    if reply_count_today >= DAILY_REPLY_CAP_PER_THREAD:
        # Hard cap — escalate.
        reply = _holding_handoff(first, coach_name)
        return await _escalate_and_reply(
            db, admin_email=admin_email, chat_room_uuid=chat_room_uuid,
            coach_name=coach_name, sender_name=student_name or "there",
            sender_email="", message=student_text, reply=reply,
            reason="daily_cap_reached", latest_id=latest_id,
            existing_sent_ids=list(sent_ids),
            existing_sent_bodies=list(sent_bodies),
        )

    # 1. Student explicitly asks for escalation
    if _wants_escalation(student_text):
        reply = _holding_handoff(first, coach_name)
        return await _escalate_and_reply(
            db, admin_email=admin_email, chat_room_uuid=chat_room_uuid,
            coach_name=coach_name, sender_name=student_name or "there",
            sender_email="", message=student_text, reply=reply,
            reason="user_requested_human", latest_id=latest_id,
            existing_sent_ids=list(sent_ids),
            existing_sent_bodies=list(sent_bodies),
        )

    # 2. Sensitive keyword (refund/complaint/urgent/etc.) — escalate + Slack
    sensitive, kw = circle_dm_bot._is_sensitive(student_text)
    if sensitive:
        reply = _holding_handoff(first, coach_name)
        return await _escalate_and_reply(
            db, admin_email=admin_email, chat_room_uuid=chat_room_uuid,
            coach_name=coach_name, sender_name=student_name or "there",
            sender_email="", message=student_text, reply=reply,
            reason=kw, latest_id=latest_id, slack_notify=True,
            existing_sent_ids=list(sent_ids),
            existing_sent_bodies=list(sent_bodies),
        )

    # 3. AI resolve via playbook
    playbook = await circle_dm_bot._get_playbook(db)
    res = await circle_dm_bot._generate_reply(
        message=student_text, sender_name=first,
        coach_name=coach_name, playbook=playbook,
    )
    reply = res["reply"]
    resolved = res["resolved"]

    if not resolved:
        # Playbook didn't cover it — escalate
        reply = _holding_handoff(first, coach_name)
        return await _escalate_and_reply(
            db, admin_email=admin_email, chat_room_uuid=chat_room_uuid,
            coach_name=coach_name, sender_name=student_name or "there",
            sender_email="", message=student_text, reply=reply,
            reason="playbook_miss", latest_id=latest_id,
            existing_sent_ids=list(sent_ids),
            existing_sent_bodies=list(sent_bodies),
        )

    # Successful AI resolve — post and stay watching
    posted = await circle_api.post_dm_message(db, admin_email, chat_room_uuid, reply)
    posted_id = _msg_id(posted) if posted else None
    new_sent_ids = list(sent_ids)
    if posted_id:
        new_sent_ids.append(posted_id)
    new_sent_bodies = list(sent_bodies)
    new_sent_bodies.append(reply)
    await _save_thread_state(db, chat_room_uuid, {
        "state": "active",
        "last_seen_message_id": max(latest_id or 0, posted_id or 0),
        "sent_message_ids": new_sent_ids[-200:],
        "sent_bodies": new_sent_bodies[-20:],
        "ai_reply_count_today": reply_count_today + 1,
        "ai_reply_count_date": today,
        "last_activity_at": datetime.now(timezone.utc).isoformat(),
        "last_reply_text": reply,
        "last_reply_at": datetime.now(timezone.utc).isoformat(),
    })
    # Audit ticket — keep low-noise: only insert one if we haven't already
    # for this thread. (We use the thread_uuid as the dedup key.)
    existing = await db.tickets.find_one(
        {"circle_dm_meta.thread_uuid": chat_room_uuid,
         "circle_dm_meta.ai_resolved": True},
        {"_id": 0, "id": 1},
    )
    if not existing:
        tid = await circle_dm_bot._create_ticket_from_dm(
            db, sender_name=student_name or "there", sender_email=None,
            coach_name=coach_name, message=student_text, ai_reply=reply,
            escalation_reason=None,
        )
        await db.tickets.update_one(
            {"id": tid},
            {"$set": {
                "status": "resolved", "priority": "low",
                "circle_dm_meta.ai_resolved": True,
                "circle_dm_meta.thread_uuid": chat_room_uuid,
            }},
        )
    return {"replied": chat_room_uuid, "posted_id": posted_id}


async def _escalate_and_reply(
    db, *, admin_email: str, chat_room_uuid: str, coach_name: str,
    sender_name: str, sender_email: str, message: str, reply: str,
    reason: str, latest_id: Optional[int], slack_notify: bool = False,
    existing_sent_ids: Optional[list[int]] = None,
    existing_sent_bodies: Optional[list[str]] = None,
) -> dict:
    posted = await circle_api.post_dm_message(db, admin_email, chat_room_uuid, reply)
    posted_id = _msg_id(posted) if posted else None
    ticket_id = await circle_dm_bot._create_ticket_from_dm(
        db, sender_name=sender_name, sender_email=sender_email,
        coach_name=coach_name, message=message, ai_reply=reply,
        escalation_reason=reason,
    )
    # Tag ticket with thread for traceability
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {"circle_dm_meta.thread_uuid": chat_room_uuid}},
    )
    if slack_notify:
        try:
            await circle_dm_bot._slack_notify_coralie_urgent(
                db, sender_name=sender_name, coach_name=coach_name,
                message=message, ticket_id=ticket_id,
            )
        except Exception as e:
            logger.warning(f"[circle-dm-poll] slack notify failed: {e}")
    sent_ids = list(existing_sent_ids or [])
    if posted_id:
        sent_ids.append(posted_id)
    sent_bodies = list(existing_sent_bodies or [])
    sent_bodies.append(reply)
    await _save_thread_state(db, chat_room_uuid, {
        "state": "escalated",
        "last_seen_message_id": max(latest_id or 0, posted_id or 0),
        "sent_message_ids": sent_ids[-200:],
        "sent_bodies": sent_bodies[-20:],
        "escalated_ticket_id": ticket_id,
        "escalation_reason": reason,
        "last_activity_at": datetime.now(timezone.utc).isoformat(),
        "escalated_at": datetime.now(timezone.utc).isoformat(),
        "last_reply_text": reply,
        "last_reply_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"escalated": chat_room_uuid, "ticket_id": ticket_id, "reason": reason}


async def _poll_one_coach(db, admin_email: str, excluded_tags_lower: set[str]) -> dict:
    """Poll a single coach admin. Returns this coach's per_coach summary."""
    per_coach = {"admin_email": admin_email, "threads_checked": 0,
                 "threads_total": 0, "actions": [], "errors": []}
    try:
        admin_member_id = await circle_api.get_cached_admin_member_id(db, admin_email)
        if not admin_member_id:
            tok = await circle_api._get_access_token(db, admin_email)
            if not tok:
                per_coach["errors"].append("auth failed")
                return per_coach
            admin_member_id = await circle_api.get_cached_admin_member_id(db, admin_email)
            if not admin_member_id:
                per_coach["errors"].append("no admin id in cache")
                return per_coach
        coach_info = await circle_api.fetch_member(admin_member_id)
        coach_name = (
            (coach_info or {}).get("name")
            or admin_email.split("@")[0].title()
        )
        threads = await circle_api.list_dm_threads(db, admin_email, per_page=100)
        dm_threads = [
            t for t in threads
            if (t.get("chat_room") or {}).get("kind") == "direct"
        ]
        per_coach["threads_checked"] = len(dm_threads)
        per_coach["threads_total"] = len(threads)
        for t in dm_threads:
            try:
                res = await _process_thread(
                    db, admin_email=admin_email,
                    admin_member_id=admin_member_id,
                    coach_name=coach_name, thread=t,
                    excluded_tags_lower=excluded_tags_lower,
                )
                per_coach["actions"].append(res)
            except Exception as e:
                logger.exception(f"[circle-dm-poll] thread errored: {e}")
                per_coach["actions"].append({"error": str(e)[:120]})
    except Exception as e:
        logger.exception(f"[circle-dm-poll] coach {admin_email} errored: {e}")
        per_coach["errors"].append(str(e)[:200])
    return per_coach


# ---------------------------------------------------------------- Poll loop
async def poll_once(db) -> dict:
    """Single poll cycle across all enabled coach admins. Runs the coach
    fetches in parallel (asyncio.gather) so 5 coaches cost ~the same wall
    time as 1 coach."""
    import asyncio
    cfg = await get_config(db)
    excluded_tags_lower = {(t or "").lower() for t in cfg.get("excluded_member_tags") or []}
    tag_excl_coaches_lower = {(e or "").lower() for e in cfg.get("tag_exclusion_coach_emails") or []}
    summary = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "enabled": cfg["enabled"],
        "coaches": [], "replied": 0, "escalated": 0, "seeded": 0,
        "human_takeover": 0, "skipped": 0, "tag_excluded": 0, "errors": [],
    }
    if not cfg["enabled"]:
        return summary

    results = await asyncio.gather(
        *[_poll_one_coach(
            db, e,
            excluded_tags_lower if e.lower() in tag_excl_coaches_lower else set(),
        ) for e in cfg["coach_emails"]],
        return_exceptions=True,
    )
    for admin_email, per_coach in zip(cfg["coach_emails"], results):
        if isinstance(per_coach, Exception):
            summary["errors"].append(f"{admin_email}: {per_coach}")
            continue
        for err in per_coach.get("errors", []):
            summary["errors"].append(f"{admin_email}: {err}")
        for res in per_coach.get("actions", []):
            if res.get("replied"):
                summary["replied"] += 1
            if res.get("escalated"):
                summary["escalated"] += 1
            if res.get("seeded"):
                summary["seeded"] += 1
            if res.get("human_takeover"):
                summary["human_takeover"] += 1
            if res.get("tag_excluded"):
                summary["tag_excluded"] += 1
            if res.get("skipped"):
                summary["skipped"] += 1
        summary["coaches"].append(per_coach)

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    await db.app_settings.update_one(
        {"id": _settings_id()},
        {"$set": {"last_poll_at": summary["finished_at"],
                  "last_poll_summary": summary}},
        upsert=True,
    )
    return summary


async def reset_thread(db, chat_room_uuid: str) -> bool:
    """Re-enable the bot on a thread that was previously escalated or taken
    over by a human. Drops the state doc so next poll seeds it fresh."""
    res = await db.circle_dm_threads.delete_one(
        {"id": f"thread:{chat_room_uuid}"},
    )
    return res.deleted_count > 0
