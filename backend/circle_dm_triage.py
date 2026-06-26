"""
Circle DM → support-ticket TRIAGE (send-free).

Restores the "Circle DM becomes a Coralie ticket" behaviour that the
auto-responder poller (circle_dm_poll) used to provide - WITHOUT any reply
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
from datetime import datetime, timezone, timedelta

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


# Automated/system Circle accounts whose DMs are notifications, not student
# questions - never make tickets from these (matched case-insensitively).
_IGNORED_SENDERS = {"do not reply bot"}


def _older_than_days(iso_ts: str, days: int) -> bool:
    """True if an ISO timestamp is older than `days`. Unparseable → False
    (treat as recent so we never silently swallow a fresh message)."""
    try:
        dt = datetime.fromisoformat((iso_ts or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt < datetime.now(timezone.utc) - timedelta(days=days)
    except Exception:
        return False


async def _triage_thread(db, admin_email, admin_member_id, coach_name, thread) -> dict:
    """Decide whether a DM thread needs a ticket - entirely from the listing's
    last_message, no per-thread fetch.

    The message sender id is a community_member_id (SAME space as the coach's
    admin_member_id), so we compare those directly. NOTE: the ids in
    other_participants_preview are a DIFFERENT id space and must NEVER be used
    for sender comparison (that was the 0-tickets bug)."""
    uuid_ = thread.get("chat_room_uuid")
    if not uuid_:
        return {"reason": "no_uuid"}

    state = await _get_thread_state(db, uuid_) or {}
    # Leave interview-eve threads to the night-before score flow.
    if state.get("interview_eve_record_id"):
        return {"reason": "interview_eve"}

    last = thread.get("last_message") or {}
    last_sender = _msg_sender_id(last)
    if last_sender is None:
        return {"reason": "no_sender"}
    if last_sender == int(admin_member_id):
        return {"reason": "coach_last"}  # coach sent the newest message → answered

    student_name = ((last.get("sender") or {}).get("name") or "").strip()
    if student_name.lower() in _IGNORED_SENDERS:
        return {"reason": "ignored_sender", "sender": student_name}

    # Unanswered: newest message is from someone other than the coach - i.e. the
    # student (their community_member_id == last_sender).
    last_at = (last.get("created_at") or "").strip()
    if not last_at:
        return {"reason": "no_timestamp"}

    baseline_at = state.get("triage_last_seen_at")
    if baseline_at and last_at <= baseline_at:
        return {"reason": "nothing_new", "last_at": last_at, "baseline_at": baseline_at}

    base_save = {
        "coach_admin_email": admin_email,
        "student_member_id": last_sender,
        "student_name": student_name,
        "triage_last_seen_at": last_at,
    }

    # First time triage sees this thread (no triage baseline yet): only ticket if
    # the message is recent - don't surface ancient dormant DMs as a burst.
    if not baseline_at and _older_than_days(last_at, 14):
        await _save_thread_state(db, uuid_, base_save)
        return {"reason": "old_seeded", "last_at": last_at}

    message_text = _msg_body(last) or "(no text)"
    student_email = None
    try:
        m = await circle_api.fetch_member_cached(db, last_sender)
        student_email = (m or {}).get("email")
        student_name = student_name or (m or {}).get("name") or ""
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
        **base_save,
        "triage_last_ticket_id": ticket_id,
        "triage_last_ticketed_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info(f"[circle-triage] ticket {ticket_id[:8]} for {student_name or last_sender} (coach {coach_name})")
    return {"reason": "ticketed", "thread": uuid_, "ticket_id": ticket_id, "student": student_name}


async def _triage_one_coach(db, admin_email: str) -> dict:
    out = {"admin_email": admin_email, "tickets": [], "errors": [], "threads": 0,
           "reasons": {}, "samples": []}
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
        coach_info = await circle_api.fetch_member_cached(db, admin_member_id)
        coach_name = (coach_info or {}).get("name") or admin_email.split("@")[0].title()
        threads = await circle_api.list_dm_threads(db, admin_email, per_page=100)
        dm_threads = [t for t in threads if (t.get("chat_room") or {}).get("kind") == "direct"]
        out["threads"] = len(dm_threads)
        for t in dm_threads:
            try:
                r = await _triage_thread(db, admin_email, admin_member_id, coach_name, t) or {}
                reason = r.get("reason", "none")
                out["reasons"][reason] = out["reasons"].get(reason, 0) + 1
                if r.get("ticket_id"):
                    out["tickets"].append(r)
                # Capture a few samples of the "almost ticketed" buckets to debug.
                if reason in ("nothing_new", "old_seeded", "no_sender", "no_timestamp") and len(out["samples"]) < 5:
                    out["samples"].append({k: r.get(k) for k in
                        ("reason", "last_at", "baseline_at")})
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
        "threads_scanned": 0,
        "tickets_created": 0,
        "tickets": [],
        "per_coach": [],
        "errors": [],
    }
    for e, r in zip(coach_emails, results):
        if isinstance(r, Exception):
            summary["errors"].append(f"{e}: {r}")
            continue
        summary["threads_scanned"] += r.get("threads") or 0
        summary["per_coach"].append({"coach": e, "threads": r.get("threads") or 0,
                                     "reasons": r.get("reasons") or {},
                                     "samples": r.get("samples") or [],
                                     "tickets": len(r.get("tickets") or [])})
        for tk in r.get("tickets") or []:
            summary["tickets_created"] += 1
            summary["tickets"].append({**tk, "coach_email": e})
        for err in r.get("errors") or []:
            summary["errors"].append(f"{e}: {err}")
    # 0 threads across ALL coaches (with tokens minting fine) almost always
    # means Circle is rate-limiting the listing call - the call swallows the
    # 429 and returns []. Surface it so it doesn't look like "nothing to do".
    if coach_emails and summary["threads_scanned"] == 0 and not summary["errors"]:
        summary["warning"] = ("0 threads for all coaches - likely Circle rate-limiting the "
                              "listing call (it returns [] on a 429). Retry in a few minutes.")
    logger.info(f"[circle-triage] done: {summary['tickets_created']} tickets, {len(summary['errors'])} errors")
    return summary
