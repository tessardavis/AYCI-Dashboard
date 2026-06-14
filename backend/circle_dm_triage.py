"""
Circle DM → support-ticket TRIAGE (send-free).

Restores the "Circle DM becomes a Coralie ticket" behaviour that the
auto-responder poller (circle_dm_poll) used to provide — WITHOUT any reply
capability. This module deliberately contains NO post_dm_message / send code,
so it can never message a student. It only READS DMs and CREATES tickets.

Independent of the banned auto-responder: enable with CIRCLE_TRIAGE_ENABLED=true
(CIRCLE_BOT_ENABLED stays off). The night-before score DM (interview_eve_dm) is
untouched, and interview-eve threads are skipped here.

Per coach inbox: list direct-message threads; for any thread whose newest
message is an unanswered student message we haven't ticketed yet, create a
support ticket (assigned to Coralie) and record a triage marker so we don't
re-ticket the same message.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import circle_api
from circle_dm_poll import (
    get_config,
    _msg_id,
    _msg_sender_id,
    _msg_body,
    _get_thread_state,
    _save_thread_state,
)

logger = logging.getLogger(__name__)


def triage_enabled() -> bool:
    return os.environ.get("CIRCLE_TRIAGE_ENABLED", "").strip().lower() == "true"


def _student_from_thread(thread: dict, admin_member_id: int):
    """(student_member_id, name) from a direct-DM thread — the participant who
    isn't the coach. Falls back to the last_message sender."""
    for p in thread.get("other_participants_preview") or []:
        if isinstance(p, dict) and p.get("id") and int(p["id"]) != int(admin_member_id):
            return int(p["id"]), (p.get("name") or "")
    lm = thread.get("last_message") or {}
    sid = _msg_sender_id(lm)
    if sid and int(sid) != int(admin_member_id):
        return int(sid), ((lm.get("sender") or {}).get("name") or "")
    return None, ""


async def _triage_thread(db, admin_email, admin_member_id, coach_name, thread) -> dict | None:
    uuid_ = thread.get("chat_room_uuid")
    if not uuid_:
        return None
    student_id, student_name = _student_from_thread(thread, admin_member_id)
    if not student_id:
        return None

    state = await _get_thread_state(db, uuid_)
    # Leave interview-eve threads to the night-before score flow.
    if state and state.get("interview_eve_record_id"):
        return None

    messages = await circle_api.list_thread_messages_for_admin(db, admin_email, uuid_, per_page=20)
    if not messages:
        return None
    messages.sort(key=lambda m: m.get("created_at") or "")
    latest = messages[-1]
    latest_id = _msg_id(latest) or 0

    # First time we've ever seen this thread: seed a marker WITHOUT ticketing
    # (so an old/dormant thread's history doesn't spam tickets on first run).
    if not state:
        await _save_thread_state(db, uuid_, {
            "coach_admin_email": admin_email,
            "student_member_id": student_id,
            "student_name": student_name,
            "triage_last_seen_id": latest_id,
            "first_seen_at": datetime.now(timezone.utc).isoformat(),
        })
        return None

    # Baseline: triage's own marker, else fall back to the (disabled) bot's
    # last_seen so DMs since the poller went off get caught on the first run.
    baseline = state.get("triage_last_seen_id")
    if baseline is None:
        baseline = state.get("last_seen_message_id") or 0

    if latest_id <= baseline:
        return None

    # Only ticket an UNANSWERED student message (the newest message is theirs).
    if _msg_sender_id(latest) != student_id:
        await _save_thread_state(db, uuid_, {"triage_last_seen_id": latest_id})
        return None

    message_text = _msg_body(latest) or "(no text)"
    student_email = None
    try:
        m = await circle_api.fetch_member(student_id)
        student_email = (m or {}).get("email")
        if not student_name:
            student_name = (m or {}).get("name") or ""
    except Exception:
        pass

    from circle_dm_bot import _create_ticket_from_dm  # lazy: avoid import cost/cycles
    ticket_id = await _create_ticket_from_dm(
        db,
        sender_name=student_name or "Circle member",
        sender_email=student_email,
        coach_name=coach_name,
        message=message_text,
        ai_reply="",  # triage never sends anything
        escalation_reason=None,
    )
    await _save_thread_state(db, uuid_, {
        "triage_last_seen_id": latest_id,
        "triage_last_ticket_id": ticket_id,
        "triage_last_ticketed_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info(f"[circle-triage] ticket {ticket_id[:8]} for {student_name or student_id} (coach {coach_name})")
    return {"thread": uuid_, "ticket_id": ticket_id, "student": student_name}


async def _triage_one_coach(db, admin_email: str) -> dict:
    out = {"admin_email": admin_email, "tickets": [], "errors": [], "threads": 0}
    try:
        admin_member_id = await circle_api.get_cached_admin_member_id(db, admin_email)
        if not admin_member_id:
            if not await circle_api._get_access_token(db, admin_email):
                out["errors"].append("auth failed")
                return out
            admin_member_id = await circle_api.get_cached_admin_member_id(db, admin_email)
            if not admin_member_id:
                out["errors"].append("no admin id")
                return out
        coach_info = await circle_api.fetch_member(admin_member_id)
        coach_name = (coach_info or {}).get("name") or admin_email.split("@")[0].title()
        threads = await circle_api.list_dm_threads(db, admin_email, per_page=100)
        dm_threads = [t for t in threads if (t.get("chat_room") or {}).get("kind") == "direct"]
        out["threads"] = len(dm_threads)
        for t in dm_threads:
            try:
                r = await _triage_thread(db, admin_email, admin_member_id, coach_name, t)
                if r:
                    out["tickets"].append(r)
            except Exception as e:
                out["errors"].append(str(e)[:120])
    except Exception as e:
        out["errors"].append(str(e)[:200])
    return out


async def triage_once(db) -> dict:
    import asyncio
    cfg = await get_config(db)
    coach_emails = cfg.get("coach_emails") or []
    results = await asyncio.gather(
        *[_triage_one_coach(db, e) for e in coach_emails],
        return_exceptions=True,
    )
    summary = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "coaches": len(coach_emails),
        "tickets_created": 0,
        "tickets": [],
        "errors": [],
    }
    for e, r in zip(coach_emails, results):
        if isinstance(r, Exception):
            summary["errors"].append(f"{e}: {r}")
            continue
        for tk in r.get("tickets") or []:
            summary["tickets_created"] += 1
            summary["tickets"].append({**tk, "coach_email": e})
        for err in r.get("errors") or []:
            summary["errors"].append(f"{e}: {err}")
    logger.info(f"[circle-triage] done: {summary['tickets_created']} tickets, {len(summary['errors'])} errors")
    return summary
