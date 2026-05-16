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
import uuid
from datetime import datetime, timedelta, timezone
import asyncio
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
        "last_poll_started_at": doc.get("last_poll_started_at"),
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


def _holding_handoff(student_first: str, coach_name: str) -> str:
    coach_first = (coach_name or "").split(" ")[0] or "the team"
    return (
        f"Hi {student_first}, thanks so much for getting in touch! 🙏 "
        f"I've got your message and the team will be in touch within 24 hours. "
        f"In the meantime, feel free to share any extra context that might help us help you faster.\n\n"
        f"Speak soon,\n{coach_first}"
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

    # Already escalated / human took over / tag-excluded — bot stays
    # silent, but for escalated threads with a linked ticket we still
    # need to *forward* any new student messages onto the ticket as
    # inbound notes. Otherwise follow-up questions from the student
    # silently vanish — Tessa/Coralie/etc only see the original
    # message in the ticket and never learn the student replied again.
    if state and state.get("state") == "escalated" and state.get("escalated_ticket_id"):
        ticket_id = state["escalated_ticket_id"]
        # Cheap fast-path: if the inline last message hasn't moved
        # past `last_seen`, nothing to forward.
        inline_last = thread.get("last_message") or {}
        inline_last_id_e = _msg_id(inline_last)
        last_seen_e = (state or {}).get("last_seen_message_id") or 0
        if inline_last_id_e is None or inline_last_id_e <= last_seen_e:
            return {"skipped": "escalated_no_new"}
        try:
            await _forward_new_msgs_to_ticket(
                db, admin_email=admin_email,
                chat_room_uuid=chat_room_uuid,
                ticket_id=ticket_id,
                student_id=student_id,
                student_name=student_name,
                admin_member_id=admin_member_id,
                last_seen=last_seen_e,
            )
        except Exception as e:
            logger.warning(
                f"[circle-dm] forward to ticket {ticket_id} failed: {e}",
            )
        return {"escalated_forwarded": chat_room_uuid}

    if state and state.get("state") in ("human_takeover", "tag_excluded"):
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
    #
    # EXCEPTION — fresh-student-message bypass: if the most-recent message
    # in this thread is a *student* message less than 10 minutes old, this
    # is almost certainly a brand-new DM that just landed (e.g. a coach
    # testing the bot, or a real student messaging a coach for the first
    # time). Seeding-and-skipping would silently swallow that first
    # message, which is bad UX. So we minimally-seed state and fall
    # through to the normal processing path. Backlog protection is
    # preserved for everything older than 10 min.
    if not state:
        inline_sender = _msg_sender_id(inline_last)
        inline_created = inline_last.get("created_at") or ""
        fresh_cutoff_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        is_fresh_student_msg = (
            inline_sender is not None
            and inline_sender != admin_member_id
            and inline_created > fresh_cutoff_iso
        )
        if not is_fresh_student_msg:
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
        # Fresh student message — seed minimal state (last_seen=0 so the
        # student message counts as "new"), then fall through to the rest
        # of _process_thread() which will fetch /messages, run the
        # lookback guard, and produce a reply.
        await _save_thread_state(db, chat_room_uuid, {
            "coach_admin_email": admin_email,
            "student_member_id": student_id,
            "student_name": student_name,
            "state": "active",
            "last_seen_message_id": 0,
            "sent_message_ids": [],
            "sent_bodies": [],
            "ai_reply_count_today": 0,
            "ai_reply_count_date": _today_str(),
            "first_seen_at": datetime.now(timezone.utc).isoformat(),
            "last_activity_at": datetime.now(timezone.utc).isoformat(),
            "first_sight_replied": True,
        })
        state = await _get_thread_state(db, chat_room_uuid) or {}
        last_seen = 0

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

    # ---- Interview-eve score capture (runs BEFORE the lookback guard) ----
    # Eve-DM threads are special: the bot is *expecting* a numeric score
    # reply from the student. If the coach has also sent a personal note
    # in the thread between the student's reply and this poll, the
    # lookback guard below would fire on the coach's message and flip the
    # thread to `human_takeover` — losing the score forever. Running the
    # score capture FIRST guarantees we record the score even when the
    # coach is actively chatting in the thread. The coach's manual reply
    # will still flip the thread to human_takeover on the next poll (via
    # the lookback guard), which is the correct end state.
    if state.get("interview_eve_record_id"):
        latest_student_msg_for_score = None
        for _m in reversed(messages):
            if _msg_sender_id(_m) == student_id:
                latest_student_msg_for_score = _m
                break
        if latest_student_msg_for_score:
            student_text_for_score = _msg_body(latest_student_msg_for_score)
            if student_text_for_score:
                try:
                    import interview_eve_dm
                    scored_early = await interview_eve_dm.maybe_record_score(
                        db, chat_room_uuid, student_text_for_score,
                    )
                    if scored_early is not None:
                        _first = (student_name or "there").split(" ")[0]
                        _coach_first = (coach_name or "").split(" ")[0] or "the team"
                        ack = (
                            f"Thanks {_first}! Got you down as "
                            f"{scored_early['score']}/10 — sending you all "
                            f"the best for tomorrow. You've got this 💪\n\n"
                            f"{_coach_first}"
                        )
                        posted_ack = await circle_api.post_dm_message(
                            db, admin_email, chat_room_uuid, ack,
                        )
                        ack_posted_id = _msg_id(posted_ack) if posted_ack else None
                        new_sent_ids = list(sent_ids)
                        if ack_posted_id:
                            new_sent_ids.append(ack_posted_id)
                        new_sent_bodies = list(sent_bodies)
                        new_sent_bodies.append(ack)
                        await _save_thread_state(db, chat_room_uuid, {
                            "state": "active",
                            "last_seen_message_id": max(
                                latest_id or 0, ack_posted_id or 0,
                            ),
                            "sent_message_ids": new_sent_ids[-200:],
                            "sent_bodies": new_sent_bodies[-20:],
                            "last_activity_at": datetime.now(timezone.utc).isoformat(),
                            "last_reply_text": ack,
                            "last_reply_at": datetime.now(timezone.utc).isoformat(),
                        })
                        return {"interview_eve_score_recorded": chat_room_uuid,
                                "score": scored_early["score"]}
                except Exception as e:
                    logger.warning(f"[interview-eve] early score capture errored: {e}")

    # Detect human takeover — scan the FULL fetched window, not just `new_messages`.
    # Why full window? Two reasons:
    #   1. A coach can reply directly in Circle's web/mobile UI. If the
    #      reply happened before `last_seen_message_id` was last bumped
    #      (e.g. our first-sight seed pinned last_seen to that very message),
    #      the polling cron would never see the admin reply as "new".
    #   2. We just shipped a `reset-stuck-threads` admin endpoint to recover
    #      from cross-environment polling races. Reset threads should
    #      auto-re-flag to `human_takeover` if a coach has been actively
    #      chatting via Circle's own UI — without that, the bot would reply
    #      on top of a live coach conversation.
    # We exclude messages whose id is in `sent_message_ids` OR whose body is
    # in `sent_bodies` so the bot doesn't flag its own previous replies as
    # takeover. We deliberately ignore messages older than 14 days so a
    # zombie 2-year-old admin message doesn't permanently silence the bot.
    # Additionally we ignore anything older than `reset_at` — when a coach
    # resets a stuck thread via the dashboard they're explicitly saying
    # "forget the past and resume normal bot behaviour".
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    cutoff_iso = (_dt.now(_tz.utc) - _td(days=14)).isoformat()
    reset_at_iso = state.get("reset_at") or ""
    if reset_at_iso and reset_at_iso > cutoff_iso:
        cutoff_iso = reset_at_iso
    for m in messages:
        if (m.get("created_at") or "") < cutoff_iso:
            continue
        sid = _msg_sender_id(m)
        mid = _msg_id(m)
        body = _msg_body(m)
        if sid == admin_member_id and mid not in sent_ids and body not in sent_bodies:
            # Breadcrumb: capture exactly which message convinced us a human
            # was talking — invaluable for post-mortems when a thread looks
            # like it should be bot-active but quietly went to human_takeover.
            # `body` is stored in full (not truncated) so the "Trust & re-arm"
            # admin tool can append it to `sent_bodies` and the next poll's
            # lookback guard will recognise it as our own message via the
            # `body not in sent_bodies` exact-match check.
            await _save_thread_state(db, chat_room_uuid, {
                "state": "human_takeover",
                "last_seen_message_id": latest_id,
                "last_activity_at": datetime.now(timezone.utc).isoformat(),
                "human_takeover_at": datetime.now(timezone.utc).isoformat(),
                "human_takeover_trigger": {
                    "message_id": mid,
                    "sender_id": sid,
                    "body": body,
                    "body_snippet": (body or "")[:200],
                    "created_at": m.get("created_at"),
                    "cutoff_iso_used": cutoff_iso,
                    "reset_at_at_time": reset_at_iso or None,
                    "sent_ids_count": len(sent_ids),
                    "sent_bodies_count": len(sent_bodies),
                },
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

    # NOTE: interview-eve score capture used to live here. Moved earlier
    # in the function (above the lookback guard) so a coach's personal
    # note in an eve-DM thread can't cause the score to be lost to a
    # premature human_takeover flag.

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
                "circle_dm_meta.coach_admin_email": admin_email,
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
    # Tag ticket with thread + posting coach for traceability (the coach
    # reply endpoint needs `coach_admin_email` so it knows which admin to
    # post the reply as).
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {
            "circle_dm_meta.thread_uuid": chat_room_uuid,
            "circle_dm_meta.coach_admin_email": admin_email,
        }},
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
                # Per-thread hard timeout so one slow thread can't hang the
                # whole coach's poll. 8s is generous — typical fetch is <500ms.
                res = await asyncio.wait_for(
                    _process_thread(
                        db, admin_email=admin_email,
                        admin_member_id=admin_member_id,
                        coach_name=coach_name, thread=t,
                        excluded_tags_lower=excluded_tags_lower,
                    ),
                    timeout=8,
                )
                per_coach["actions"].append(res)
            except asyncio.TimeoutError:
                logger.warning(f"[circle-dm-poll] thread {t.get('chat_room_uuid')} timed out (>8s)")
                per_coach["actions"].append({"timeout": t.get("chat_room_uuid")})
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
    started_at = datetime.now(timezone.utc).isoformat()
    # Persist `last_poll_started_at` IMMEDIATELY so the dashboard can show
    # "poll in progress" instead of stuck-at-old-timestamp during a long
    # poll cycle. Also useful for telling apart "poll hung" from "scheduler
    # never fired" — a stale started_at means the scheduler isn't even
    # triggering; a fresh started_at means it triggered but is hung.
    await db.app_settings.update_one(
        {"id": _settings_id()},
        {"$set": {"last_poll_started_at": started_at}},
        upsert=True,
    )
    summary = {
        "started_at": started_at,
        "enabled": cfg["enabled"],
        "coaches": [], "replied": 0, "escalated": 0, "seeded": 0,
        "human_takeover": 0, "skipped": 0, "tag_excluded": 0, "errors": [],
    }
    if not cfg["enabled"]:
        return summary

    # Hard cap each coach's fetch loop at 60s so one slow coach can't hang
    # the whole poll. Per-thread timeout is 8s but `_poll_one_coach`
    # iterates serially through hundreds of threads, so total per-coach
    # cap is the safety net.
    async def _coach_with_timeout(e: str) -> dict:
        scoped_tags = excluded_tags_lower if e.lower() in tag_excl_coaches_lower else set()
        try:
            return await asyncio.wait_for(
                _poll_one_coach(db, e, scoped_tags),
                timeout=60,
            )
        except asyncio.TimeoutError:
            logger.warning(f"[circle-dm-poll] coach {e} timed out after 60s")
            return {"actions": [], "errors": [f"{e}: coach-level timeout"], "threads_checked": 0, "threads_total": 0}

    results = await asyncio.gather(
        *[_coach_with_timeout(e) for e in cfg["coach_emails"]],
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
            if res.get("escalated_forwarded"):
                summary["escalated_forwarded"] = summary.get("escalated_forwarded", 0) + 1
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


async def _forward_new_msgs_to_ticket(
    db, *, admin_email: str, chat_room_uuid: str, ticket_id: str,
    student_id: int, student_name: str, admin_member_id: int,
    last_seen: int,
) -> None:
    """For an *escalated* thread, fetch any messages newer than
    `last_seen` and append student messages to the linked support
    ticket as inbound notes. Also bumps `last_seen_message_id` so we
    don't re-import on the next poll, and re-opens the ticket if it
    was closed.

    Only forwards messages sent by the STUDENT — admin replies (made by
    the team in Circle) aren't pushed back into the ticket because they
    might create a confusing loop with Coralie's own reply work.
    """
    import circle_api
    messages = await circle_api.list_thread_messages_for_admin(
        db, admin_email, chat_room_uuid, per_page=20,
    )
    if not messages:
        return
    messages.sort(key=lambda m: m.get("created_at") or "")
    latest_id = _msg_id(messages[-1]) or 0
    new_student_msgs: list[dict] = []
    for m in messages:
        mid = _msg_id(m)
        if mid is None or mid <= last_seen:
            continue
        sid = _msg_sender_id(m)
        if sid != student_id:
            continue
        body = _msg_body(m)
        if not body:
            continue
        new_student_msgs.append({"id": mid, "body": body,
                                  "created_at": m.get("created_at")})

    # Always bump last_seen even when nothing was forwarded (e.g. the
    # only new messages were admin replies) so we don't keep re-fetching
    # the same window on every poll.
    if latest_id > last_seen:
        await db.circle_dm_threads.update_one(
            {"id": f"thread:{chat_room_uuid}"},
            {"$set": {
                "last_seen_message_id": latest_id,
                "last_activity_at": datetime.now(timezone.utc).isoformat(),
            }},
        )

    if not new_student_msgs:
        return

    # Make sure we don't double-append the same message if a prior
    # forwarding run inserted it but the last_seen update raced.
    existing = await db.tickets.find_one(
        {"id": ticket_id},
        {"_id": 0, "notes.circle_message_id": 1, "status": 1},
    )
    if not existing:
        logger.warning(
            f"[circle-dm] thread {chat_room_uuid} escalated_ticket_id "
            f"{ticket_id} not found in tickets — skipping forward.",
        )
        return
    already_forwarded_ids = {
        (n or {}).get("circle_message_id")
        for n in (existing.get("notes") or [])
        if (n or {}).get("circle_message_id")
    }

    notes_to_push: list[dict] = []
    for m in new_student_msgs:
        if m["id"] in already_forwarded_ids:
            continue
        notes_to_push.append({
            "id": str(uuid.uuid4()),
            "author_id": "_circle_dm",
            "author_name": f"{student_name} (Circle DM)",
            "body": m["body"],
            "created_at": m["created_at"] or datetime.now(timezone.utc).isoformat(),
            "internal": True,
            "circle_message_id": m["id"],
        })

    if not notes_to_push:
        return

    now = datetime.now(timezone.utc).isoformat()
    await db.tickets.update_one(
        {"id": ticket_id},
        {
            "$push": {"notes": {"$each": notes_to_push}},
            "$set": {
                "updated_at": now,
                "status": "open" if existing.get("status") in (
                    "resolved", "closed") else existing.get("status") or "open",
            },
        },
    )
    logger.info(
        f"[circle-dm] forwarded {len(notes_to_push)} student message(s) "
        f"to ticket {ticket_id} from thread {chat_room_uuid}",
    )


async def reset_thread(db, chat_room_uuid: str) -> bool:
    """Re-enable the bot on a thread that was previously escalated or taken
    over by a human.

    Important: we DON'T delete the state doc — that would wipe
    `sent_message_ids` / `sent_bodies` and the next poll's lookback guard
    would treat the bot's own previous replies (or any admin message in
    the last 14 days) as "human is here, back off" and immediately re-flag
    the thread as `human_takeover`. Instead, do an in-place reset that
    flips state back to `active`, clears the escalation/takeover markers,
    and stamps `reset_at` so the lookback guard ignores anything before
    this moment. The bot's own previous replies remain in `sent_message_ids`
    so they're still recognised, and any older coach replies are ignored
    via the reset_at cutoff."""
    now = datetime.now(timezone.utc).isoformat()
    res = await db.circle_dm_threads.update_one(
        {"id": f"thread:{chat_room_uuid}"},
        {
            "$set": {
                "state": "active",
                "human_takeover_at": None,
                "human_takeover_by": None,
                "escalated_at": None,
                "last_activity_at": now,
                "reset_at": now,
            },
        },
    )
    return res.modified_count > 0 or res.matched_count > 0


async def trust_takeover_trigger(db, chat_room_uuid: str) -> dict:
    """One-click recovery for a thread that flipped to `human_takeover`
    because of a cross-environment race (or any false-positive admin
    message).

    Reads the persisted `human_takeover_trigger` breadcrumb, appends the
    triggering message's full body to `sent_bodies` AND its id to
    `sent_message_ids`, then re-arms the thread so the bot resumes. The
    next poll's lookback guard will recognise the same message as the
    bot's own (`mid in sent_ids OR body in sent_bodies`) and not flip
    back to takeover.

    Returns a small dict for the API to relay to the caller.
    """
    state = await db.circle_dm_threads.find_one(
        {"id": f"thread:{chat_room_uuid}"}, {"_id": 0},
    )
    if not state:
        return {"ok": False, "reason": "no_state_doc"}
    if state.get("state") != "human_takeover":
        return {"ok": False, "reason": "not_in_human_takeover",
                "current_state": state.get("state")}
    trigger = state.get("human_takeover_trigger") or {}
    body = trigger.get("body")
    if not body:
        # Older takeovers (pre-breadcrumb) won't have the full body — the
        # admin should use plain Re-arm in that case.
        return {"ok": False, "reason": "no_trigger_body_recorded"}
    mid = trigger.get("message_id")

    sent_bodies = list(state.get("sent_bodies") or [])
    if body not in sent_bodies:
        sent_bodies.append(body)
    sent_ids = list(state.get("sent_message_ids") or [])
    if mid and mid not in sent_ids:
        sent_ids.append(mid)

    now = datetime.now(timezone.utc).isoformat()
    await db.circle_dm_threads.update_one(
        {"id": f"thread:{chat_room_uuid}"},
        {
            "$set": {
                "state": "active",
                "human_takeover_at": None,
                "human_takeover_by": None,
                "human_takeover_trigger": None,
                "last_activity_at": now,
                "reset_at": now,
                "sent_bodies": sent_bodies[-20:],
                "sent_message_ids": sent_ids[-200:],
                "trust_takeover_at": now,
            },
        },
    )
    return {
        "ok": True,
        "trusted_message_id": mid,
        "trusted_body_chars": len(body),
        "sent_bodies_count": len(sent_bodies),
        "sent_message_ids_count": len(sent_ids),
    }


# ---------------------------------------------------------- Non-mutating trace
async def trace_thread(
    db,
    *,
    thread_uuid: Optional[str] = None,
    coach_email: Optional[str] = None,
    student_search: Optional[str] = None,
) -> dict:
    """READ-ONLY simulation of ``_process_thread()``.

    Walks every gate the bot would walk for a single thread and returns a
    step-by-step trace + the *exact* conclusion the bot would reach. Nothing
    is mutated — no state writes, no Circle POSTs, no LLM calls. Designed
    for the "why didn't the bot reply to *this* thread?" debugging loop.

    Lookup priority:
      • ``thread_uuid`` (+ optional ``coach_email``) — exact UUID lookup
      • ``student_search`` — substring-matches the *other-participant* name
        across every configured coach's DM list; picks the most recently
        active match. Useful when you don't know the UUID off-hand.
    """
    import circle_api
    cfg = await get_config(db)

    if not (thread_uuid or student_search):
        return {"found": False, "error": "pass thread_uuid or student_search"}

    coaches: list[str] = (
        [coach_email.strip().lower()]
        if coach_email else list(cfg["coach_emails"])
    )

    target_thread: Optional[dict] = None
    target_coach: Optional[str] = None
    target_admin_id: Optional[int] = None
    search_log: list[dict] = []

    for c in coaches:
        admin_id = await circle_api.get_cached_admin_member_id(db, c)
        if not admin_id:
            tok = await circle_api._get_access_token(db, c)
            if tok:
                admin_id = await circle_api.get_cached_admin_member_id(db, c)
        threads = await circle_api.list_dm_threads(db, c, per_page=100)
        dm_threads = [t for t in threads if (t.get("chat_room") or {}).get("kind") == "direct"]
        search_log.append({"coach": c, "admin_id": admin_id,
                           "total_threads": len(threads),
                           "dm_threads": len(dm_threads)})

        if thread_uuid:
            for t in dm_threads:
                if t.get("chat_room_uuid") == thread_uuid:
                    target_thread, target_coach, target_admin_id = t, c, admin_id
                    break
        elif student_search:
            needle = student_search.lower()
            candidates = []
            for t in dm_threads:
                for p in t.get("other_participants_preview") or []:
                    name = (p.get("name") or "")
                    if needle in name.lower():
                        candidates.append(t)
                        break
            if candidates:
                # Pick the most recently active match
                candidates.sort(
                    key=lambda t: (t.get("last_message") or {}).get("created_at") or "",
                    reverse=True,
                )
                target_thread, target_coach, target_admin_id = candidates[0], c, admin_id
        if target_thread:
            break

    if not target_thread:
        return {
            "found": False,
            "search_log": search_log,
            "conclusion": (
                "Thread not visible in any configured coach's DM list. The bot "
                "can only process threads returned by Circle's Headless API. "
                "Possible causes: (a) wrong coach inbox, (b) Circle hiding the "
                "thread from the API, (c) the coach's CIRCLE_USER_TOKEN is "
                "scoped to a different community."
            ),
        }

    steps: list[dict] = []
    chat_room_uuid = target_thread.get("chat_room_uuid")
    steps.append({
        "step": "thread_found",
        "chat_room_uuid": chat_room_uuid,
        "coach_admin_email": target_coach,
        "admin_member_id": target_admin_id,
        "search_log": search_log,
    })

    student_id, student_name = _identify_student(target_thread, target_admin_id or 0)
    steps.append({
        "step": "identify_student",
        "student_member_id": student_id,
        "student_name": student_name,
        "other_participants": target_thread.get("other_participants_preview") or [],
    })
    if not student_id:
        return {"found": True, "trace": steps,
                "conclusion": "WOULD SKIP: no student identified (only the admin is in this thread)."}

    state = await _get_thread_state(db, chat_room_uuid)
    steps.append({
        "step": "load_state",
        "has_state": bool(state),
        "current_state": (state or {}).get("state"),
        "last_seen_message_id": (state or {}).get("last_seen_message_id"),
        "reset_at": (state or {}).get("reset_at"),
        "human_takeover_at": (state or {}).get("human_takeover_at"),
        "human_takeover_trigger": (state or {}).get("human_takeover_trigger"),
        "sent_message_ids_count": len((state or {}).get("sent_message_ids") or []),
        "sent_bodies_count": len((state or {}).get("sent_bodies") or []),
        "ai_reply_count_today": (state or {}).get("ai_reply_count_today"),
        "ai_reply_count_date": (state or {}).get("ai_reply_count_date"),
    })

    if state and state.get("state") in ("escalated", "human_takeover", "tag_excluded"):
        return {
            "found": True, "trace": steps,
            "conclusion": (
                f"WOULD SKIP: state={state['state']}. Bot has explicitly "
                f"backed off. Use Re-arm on this thread to re-engage."
            ),
        }

    inline_last = target_thread.get("last_message") or {}
    inline_last_id = _msg_id(inline_last)
    last_seen = (state or {}).get("last_seen_message_id") or 0
    steps.append({
        "step": "fast_path_check",
        "inline_last_id": inline_last_id,
        "last_seen": last_seen,
        "inline_last_sender": (inline_last.get("sender") or {}).get("name"),
        "inline_last_sender_id": _msg_sender_id(inline_last),
        "inline_last_body": _msg_body(inline_last)[:200],
        "inline_last_created_at": inline_last.get("created_at"),
    })
    if state and inline_last_id is not None and inline_last_id <= last_seen:
        return {
            "found": True, "trace": steps,
            "conclusion": (
                f"WOULD SKIP: no_new (inline_last_id={inline_last_id} "
                f"<= last_seen={last_seen}). The inline last_message in the "
                f"thread-list response is older than the bot's high-water "
                f"mark — either no new message arrived, or a previous poll "
                f"already advanced last_seen past it."
            ),
        }

    if not state:
        from datetime import datetime as _dt2, timezone as _tz2, timedelta as _td2
        inline_sender_for_seed = _msg_sender_id(inline_last)
        inline_created_for_seed = inline_last.get("created_at") or ""
        fresh_cutoff_iso = (_dt2.now(_tz2.utc) - _td2(minutes=10)).isoformat()
        is_fresh_student_msg = (
            inline_sender_for_seed is not None
            and inline_sender_for_seed != target_admin_id
            and inline_created_for_seed > fresh_cutoff_iso
        )
        steps.append({
            "step": "first_sight_check",
            "inline_sender_id": inline_sender_for_seed,
            "inline_created_at": inline_created_for_seed,
            "fresh_cutoff_iso": fresh_cutoff_iso,
            "is_fresh_student_msg": is_fresh_student_msg,
        })
        if not is_fresh_student_msg:
            return {
                "found": True, "trace": steps,
                "conclusion": (
                    f"WOULD SEED (no reply): no state doc exists AND the "
                    f"inline last_message isn't a fresh (<10 min) student "
                    f"message. First poll will record "
                    f"last_seen_message_id={inline_last_id} *without* "
                    f"replying. Send another DM after seeding to trigger a "
                    f"reply."
                ),
            }
        # else: bot WOULD minimally-seed and continue to a real reply.
        # The trace simulates this by treating last_seen=0 so the inline
        # student message counts as "new" below.
        last_seen = 0
        state = {}

    messages = await circle_api.list_thread_messages_for_admin(
        db, target_coach, chat_room_uuid, per_page=20,
    )
    if not messages:
        return {"found": True, "trace": steps,
                "conclusion": "WOULD SKIP: no_messages (Circle returned empty)."}

    messages.sort(key=lambda m: m.get("created_at") or "")
    latest_id = _msg_id(messages[-1])
    sent_ids_set = set(state.get("sent_message_ids") or [])
    sent_bodies_set = set(state.get("sent_bodies") or [])

    msg_summary = [{
        "id": _msg_id(m),
        "sender_id": _msg_sender_id(m),
        "sender_name": (m.get("sender") or {}).get("name"),
        "is_admin": _msg_sender_id(m) == target_admin_id,
        "is_student": _msg_sender_id(m) == student_id,
        "body": _msg_body(m)[:200],
        "created_at": m.get("created_at"),
        "in_sent_ids": _msg_id(m) in sent_ids_set,
        "in_sent_bodies": _msg_body(m) in sent_bodies_set,
    } for m in messages]
    steps.append({"step": "fetch_messages", "count": len(messages), "messages": msg_summary})

    new_messages = [m for m in messages if _msg_id(m) is not None and _msg_id(m) > last_seen]
    steps.append({
        "step": "filter_new",
        "latest_id": latest_id,
        "new_count": len(new_messages),
        "new_ids": [_msg_id(m) for m in new_messages],
    })
    if not new_messages:
        return {
            "found": True, "trace": steps,
            "conclusion": (
                f"WOULD SKIP: no_new (no fetched message has id > "
                f"last_seen={last_seen}). The inline last_message said "
                f"id={inline_last_id} but the full /messages fetch didn't "
                f"return anything newer than last_seen. Possible: the test "
                f"message was edited/deleted, or Circle is paginating it "
                f"out of the first 20."
            ),
        }

    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    cutoff_iso = (_dt.now(_tz.utc) - _td(days=14)).isoformat()
    reset_at_iso = state.get("reset_at") or ""
    if reset_at_iso and reset_at_iso > cutoff_iso:
        cutoff_iso = reset_at_iso
    steps.append({
        "step": "lookback_guard_setup",
        "cutoff_iso": cutoff_iso,
        "reset_at_iso": reset_at_iso,
    })

    triggered = None
    for m in messages:
        if (m.get("created_at") or "") < cutoff_iso:
            continue
        sid = _msg_sender_id(m)
        mid = _msg_id(m)
        body = _msg_body(m)
        if sid == target_admin_id and mid not in sent_ids_set and body not in sent_bodies_set:
            triggered = {
                "message_id": mid,
                "sender_id": sid,
                "sender_name": (m.get("sender") or {}).get("name"),
                "body_snippet": body[:200],
                "created_at": m.get("created_at"),
                "reason": "admin message not in sent_message_ids AND not in sent_bodies",
            }
            break
    if triggered:
        steps.append({"step": "lookback_guard_triggered", "trigger": triggered})
        return {
            "found": True, "trace": steps,
            "conclusion": (
                "WOULD FLAG human_takeover: the lookback guard sees an admin "
                "message inside the window that the bot doesn't recognise as "
                "its own. Either the coach posted manually in Circle, or the "
                "bot replied from a different env (preview vs production) "
                "and the current env's sent_message_ids / sent_bodies don't "
                "know about it. Fix: bulk Reset Stuck Threads, or Re-arm + "
                "send a fresh test message."
            ),
        }
    steps.append({"step": "lookback_guard_passed"})

    latest_student_msg = None
    for m in reversed(new_messages):
        if _msg_sender_id(m) == student_id:
            latest_student_msg = m
            break
    if not latest_student_msg:
        return {
            "found": True, "trace": steps,
            "conclusion": (
                "WOULD SKIP: no_student_msg (all new messages came from the "
                "bot itself — nothing to react to)."
            ),
        }
    student_text = _msg_body(latest_student_msg)
    steps.append({
        "step": "found_student_msg",
        "id": _msg_id(latest_student_msg),
        "body": student_text[:400],
        "created_at": latest_student_msg.get("created_at"),
    })
    if not student_text:
        return {"found": True, "trace": steps, "conclusion": "WOULD SKIP: empty_body."}

    today = _today_str()
    reply_count_today = (
        state.get("ai_reply_count_today", 0)
        if state.get("ai_reply_count_date") == today else 0
    )
    if reply_count_today >= DAILY_REPLY_CAP_PER_THREAD:
        return {
            "found": True, "trace": steps,
            "conclusion": (
                f"WOULD ESCALATE: daily_cap_reached "
                f"({reply_count_today}/{DAILY_REPLY_CAP_PER_THREAD})."
            ),
        }

    if _wants_escalation(student_text):
        return {"found": True, "trace": steps,
                "conclusion": "WOULD ESCALATE: user_requested_human (matched an escalation phrase)."}

    try:
        import circle_dm_bot
        sensitive, kw = circle_dm_bot._is_sensitive(student_text)
    except Exception as e:
        sensitive, kw = False, f"(sensitive check errored: {e})"
    if sensitive:
        return {"found": True, "trace": steps,
                "conclusion": f"WOULD ESCALATE: sensitive keyword ({kw}). Slack notification fires."}

    excluded_tags_lower = {(t or "").lower() for t in cfg.get("excluded_member_tags") or []}
    tag_excl_coaches_lower = {(e or "").lower() for e in cfg.get("tag_exclusion_coach_emails") or []}
    if (target_coach or "").lower() in tag_excl_coaches_lower and excluded_tags_lower:
        member = await circle_api.fetch_member_cached(db, student_id)
        student_tags_raw = (member or {}).get("tags") or []
        student_tags_lower = [(t or "").lower() for t in student_tags_raw]
        matched = [t for t in student_tags_lower if t in excluded_tags_lower]
        steps.append({
            "step": "tag_check",
            "student_tags": student_tags_raw,
            "excluded_tags_config": list(excluded_tags_lower),
            "matched_excluded": matched,
        })
        if matched:
            return {
                "found": True, "trace": steps,
                "conclusion": f"WOULD SKIP: tag_excluded — student carries excluded tag(s): {matched}",
            }
    else:
        steps.append({
            "step": "tag_check_scoped_out",
            "reason": (
                f"coach {target_coach} is not in tag_exclusion_coach_emails "
                f"({sorted(tag_excl_coaches_lower)}) — tags ignored for this coach"
            ),
        })

    return {
        "found": True, "trace": steps,
        "conclusion": (
            "WOULD REPLY (or escalate via playbook). The bot would post an "
            "AI reply. If the real bot is silent on this thread, the failure "
            "is downstream of these gates — likely: (a) Circle rejecting the "
            "POST (token revoked / wrong admin), (b) the asyncio polling "
            "loop died, or (c) the playbook LLM call is timing out. Trigger "
            "'Poll Now' from Settings and check last_poll_summary."
        ),
    }
