"""Circle community webhook routes — receives DMs from Circle Workflows and
hands them to the AI bot for triage/reply."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import circle_dm_bot
from db import db
from deps import require_admin, require_board

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/circle", tags=["circle"])


def _verify_signature(raw_body: bytes, signature: str | None) -> bool:
    """Verify the HMAC-SHA256 signature Circle's webhook sends with each call.
    Configured at workflow setup time in Circle's UI as `X-Circle-Signature`."""
    secret = os.environ.get("CIRCLE_DM_WEBHOOK_SECRET") or ""
    if not secret:
        # No secret configured — accept any call (dev mode). In production
        # the admin should set CIRCLE_DM_WEBHOOK_SECRET in .env so unsigned
        # requests are rejected.
        return True
    if not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/dm-webhook")
async def circle_dm_webhook(request: Request, background: BackgroundTasks):
    """Called by the Circle Workflow on every inbound DM to a coach.
    Returns `{reply_text, escalated, ai_resolved, ticket_id}` — Circle's
    next workflow step references `{{ webhook.response.reply_text }}` to send
    the reply from the coach's own account.

    No auth — Circle Workflows can't pass session cookies. Signed via
    `X-Circle-Signature` HMAC instead (see _verify_signature)."""
    raw = await request.body()
    if not _verify_signature(raw, request.headers.get("X-Circle-Signature")):
        raise HTTPException(401, "Invalid signature")
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    # Audit-log the raw event so admins can replay/debug from MongoDB
    await db.circle_dm_events.insert_one({
        "received_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    })

    try:
        return await circle_dm_bot.handle_dm_webhook(db, payload, background)
    except Exception as e:
        logger.exception(f"[circle-dm-webhook] handler crashed: {e}")
        # Fail open: send the holding reply so the student isn't ignored
        return {
            "reply_text": "Hi there, thanks for reaching out — I've passed your message to the team and they'll respond within 24h.\nBest, AYCI Team",
            "escalated": True,
            "ai_resolved": False,
            "ticket_id": None,
            "error": "handler_crashed",
        }


# --- Coach Playbook (admin-editable text used as the bot's knowledge base) --
class PlaybookUpdate(BaseModel):
    text: str = Field(..., min_length=10, max_length=8000)


@router.get("/coach-playbook")
async def get_coach_playbook(user: dict = Depends(require_board("bot"))):
    doc = await db.app_settings.find_one({"id": "coach_playbook"}, {"_id": 0, "text": 1, "updated_at": 1, "updated_by_name": 1})
    return {
        "text": (doc or {}).get("text") or circle_dm_bot.DEFAULT_PLAYBOOK,
        "is_default": not doc,
        "updated_at": (doc or {}).get("updated_at"),
        "updated_by_name": (doc or {}).get("updated_by_name"),
    }


@router.put("/coach-playbook")
async def update_coach_playbook(
    body: PlaybookUpdate, user: dict = Depends(require_board("bot")),
):
    await db.app_settings.update_one(
        {"id": "coach_playbook"},
        {"$set": {
            "id": "coach_playbook",
            "text": body.text.strip(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by_name": user.get("name"),
        }},
        upsert=True,
    )
    return {"ok": True}


# --- Recent DM events (admin debug view) ------------------------------------
@router.get("/dm-events")
async def list_dm_events(user: dict = Depends(require_board("bot")), limit: int = 30):
    """Last N raw webhook payloads we received from Circle. Useful for
    debugging the Workflow setup and seeing exactly what Circle sends us."""
    rows = await db.circle_dm_events.find(
        {}, {"_id": 0},
    ).sort("received_at", -1).limit(min(max(1, limit), 100)).to_list(100)
    return {"events": rows}


# --- DM Bot polling (v2) ----------------------------------------------------
class BotConfigUpdate(BaseModel):
    enabled: bool | None = None
    coach_emails: list[str] | None = None
    excluded_member_tags: list[str] | None = None
    tag_exclusion_coach_emails: list[str] | None = None


@router.get("/bot/status")
async def bot_status(user: dict = Depends(require_board("bot"))):
    """Polling bot status + recent thread state. Used by Settings → Bot tab."""
    import circle_dm_poll
    cfg = await circle_dm_poll.get_config(db)
    threads = await db.circle_dm_threads.find(
        {}, {"_id": 0},
    ).sort("last_activity_at", -1).limit(50).to_list(50)
    return {
        "config": {k: cfg.get(k) for k in ("enabled", "coach_emails", "excluded_member_tags", "tag_exclusion_coach_emails")},
        "last_poll_at": cfg.get("last_poll_at"),
        "last_poll_summary": cfg.get("last_poll_summary") or {},
        "threads": threads,
    }


@router.put("/bot/config")
async def bot_config_update(body: BotConfigUpdate, user: dict = Depends(require_board("bot"))):
    import circle_dm_poll
    cfg = await circle_dm_poll.set_config(
        db, enabled=body.enabled, coach_emails=body.coach_emails,
        excluded_member_tags=body.excluded_member_tags,
        tag_exclusion_coach_emails=body.tag_exclusion_coach_emails,
    )
    return {"ok": True, "config": {k: cfg.get(k) for k in ("enabled", "coach_emails", "excluded_member_tags", "tag_exclusion_coach_emails")}}


@router.post("/bot/poll-now")
async def bot_poll_now(user: dict = Depends(require_board("bot"))):
    """Force a single poll cycle for testing without waiting for the cron."""
    import circle_dm_poll
    return await circle_dm_poll.poll_once(db)


@router.post("/bot/reset-thread/{thread_uuid}")
async def bot_reset_thread(thread_uuid: str, user: dict = Depends(require_board("bot"))):
    """Drop the state doc for a thread so the bot re-engages on the next poll
    (seeds fresh — doesn't reply to backlog, only to new messages)."""
    import circle_dm_poll
    ok = await circle_dm_poll.reset_thread(db, thread_uuid)
    return {"ok": ok}


@router.get("/bot/diagnose")
async def bot_diagnose(user: dict = Depends(require_board("bot"))):
    """Read-only snapshot of every coach admin's DM inbox as Circle's
    Headless API sees it. Use this to verify a test DM actually landed in
    the right inbox before troubleshooting the bot itself."""
    import circle_api
    import circle_dm_poll
    cfg = await circle_dm_poll.get_config(db)
    out = {"coaches": []}
    for admin_email in cfg["coach_emails"]:
        admin_id = await circle_api.get_cached_admin_member_id(db, admin_email)
        if not admin_id:
            tok = await circle_api._get_access_token(db, admin_email)
            if tok:
                admin_id = await circle_api.get_cached_admin_member_id(db, admin_email)
        threads = await circle_api.list_dm_threads(db, admin_email, per_page=100)
        dms = [t for t in threads if (t.get("chat_room") or {}).get("kind") == "direct"]
        rows = []
        for t in dms:
            participants = t.get("other_participants_preview") or []
            other = next(
                (p for p in participants
                 if p.get("community_member_id") and int(p["community_member_id"]) != int(admin_id or 0)),
                None,
            )
            lm = t.get("last_message") or {}
            rows.append({
                "uuid": t.get("chat_room_uuid"),
                "with": (other or {}).get("name"),
                "with_member_id": (other or {}).get("community_member_id"),
                "with_email": (other or {}).get("email"),
                "last_activity_at": lm.get("created_at") or lm.get("sent_at"),
                "last_body": (lm.get("body") or "")[:120],
                "last_sender": (lm.get("sender") or {}).get("name"),
                "unread": t.get("unread_messages_count") or 0,
            })
        rows.sort(key=lambda r: r["last_activity_at"] or "", reverse=True)
        out["coaches"].append({
            "admin_email": admin_email,
            "admin_member_id": admin_id,
            "total_threads": len(threads),
            "dm_threads": len(dms),
            "recent_dms": rows[:15],
        })
    return out


# --- Coach reply from a Circle DM ticket back into Circle ------------------
class CircleTicketReplyBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


@router.post("/tickets/{ticket_id}/reply")
async def reply_to_circle_ticket(
    ticket_id: str,
    payload: CircleTicketReplyBody,
    user: dict = Depends(require_board("tickets")),
):
    """Coach reply from the Tickets board → posts into the original Circle
    DM thread as the watching coach admin. Records the reply on the ticket's
    notes timeline AND marks the bot's thread state as `human_takeover` so
    the AI doesn't try to auto-reply on top of the coach.
    """
    import circle_api
    import circle_dm_poll
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Ticket not found")
    if (t.get("source") or "") != "circle_dm":
        raise HTTPException(400, "Not a Circle DM ticket")
    meta = t.get("circle_dm_meta") or {}
    thread_uuid = meta.get("thread_uuid")
    if not thread_uuid:
        raise HTTPException(400, "Ticket missing circle_dm_meta.thread_uuid — can't route back to Circle")

    # Which admin to post as? Whichever coach is configured to watch this DM
    # (currently a single value in cfg.coach_emails). If empty, fail loudly.
    cfg = await circle_dm_poll.get_config(db)
    if not cfg["coach_emails"]:
        raise HTTPException(400, "No coach admin configured in Settings → Bot")
    admin_email = cfg["coach_emails"][0]

    body = payload.body.strip()
    posted = await circle_api.post_dm_message(db, admin_email, thread_uuid, body)
    if posted is None:
        raise HTTPException(502, "Circle rejected the message — see backend logs")

    now = datetime.now(timezone.utc).isoformat()
    note = {
        "id": __import__("uuid").uuid4().hex,
        "author_id": "_circle_dm_outbound",
        "author_name": user.get("name") or user.get("email") or "Coach",
        "body": body,
        "created_at": now,
        "internal": False,
        "attachments": [],
    }
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$push": {"notes": note}, "$set": {"updated_at": now}},
    )

    # Stop the bot from auto-replying on this thread now that a human is in.
    # We also remember the body so a future poll that picks up this same
    # message (echoed back) doesn't trigger a redundant `human_takeover`.
    state = await db.circle_dm_threads.find_one({"thread_uuid": thread_uuid}, {"_id": 0})
    sent_bodies = (state or {}).get("sent_bodies") or []
    sent_bodies.append(body)
    await db.circle_dm_threads.update_one(
        {"id": f"thread:{thread_uuid}"},
        {"$set": {
            "id": f"thread:{thread_uuid}",
            "thread_uuid": thread_uuid,
            "state": "human_takeover",
            "sent_bodies": sent_bodies[-20:],
            "human_takeover_at": now,
            "human_takeover_by": user.get("email"),
            "last_activity_at": now,
            "last_reply_text": body,
            "last_reply_at": now,
        }},
        upsert=True,
    )

    fresh = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    return {"ok": True, "posted_as": admin_email, "ticket": fresh}


# --- Playbook suggestions (self-improving bot) -----------------------------
@router.get("/bot/playbook-suggestions")
async def list_playbook_suggestions(user: dict = Depends(require_board("bot")), limit: int = 30):
    """Tickets the bot escalated with reason=playbook_miss that haven't been
    dismissed yet. These are real student questions the playbook could be
    extended to cover. Returns the question, ticket id, student name, and
    timestamp."""
    rows = await db.tickets.find(
        {
            "source": "circle_dm",
            "circle_dm_meta.escalation_reason": "playbook_miss",
            "circle_dm_meta.suggestion_status": {"$ne": "dismissed"},
        },
        {"_id": 0, "id": 1, "student_name": 1, "circle_dm_meta": 1,
         "created_at": 1, "status": 1, "subject": 1},
    ).sort("created_at", -1).limit(min(max(1, limit), 100)).to_list(100)
    out = []
    for r in rows:
        meta = r.get("circle_dm_meta") or {}
        out.append({
            "ticket_id": r.get("id"),
            "subject": r.get("subject"),
            "student_name": r.get("student_name"),
            "question": meta.get("original_message")
                        or (r.get("subject") or "").replace("Circle DM to Tessa Davis: ", ""),
            "coach_name": meta.get("coach_name"),
            "created_at": r.get("created_at"),
            "ticket_status": r.get("status"),
            "suggestion_status": meta.get("suggestion_status") or "pending",
        })
    return {"suggestions": out}


class PlaybookSuggestionAction(BaseModel):
    answer: str | None = None  # required when action=accept
    action: str = "accept"      # "accept" | "dismiss"


@router.post("/bot/playbook-suggestions/{ticket_id}/handle")
async def handle_playbook_suggestion(
    ticket_id: str, body: PlaybookSuggestionAction,
    user: dict = Depends(require_board("bot")),
):
    """Either dismiss the suggestion (no playbook change), or accept it by
    appending a new Q/A pair to the coach playbook and marking the ticket
    as handled."""
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Ticket not found")
    meta = t.get("circle_dm_meta") or {}
    question = meta.get("original_message") or (t.get("subject") or "").replace(
        f"Circle DM to {meta.get('coach_name') or 'Coach'}: ", "",
    )
    now = datetime.now(timezone.utc).isoformat()

    if body.action == "dismiss":
        await db.tickets.update_one(
            {"id": ticket_id},
            {"$set": {"circle_dm_meta.suggestion_status": "dismissed",
                      "circle_dm_meta.suggestion_handled_at": now,
                      "updated_at": now}},
        )
        return {"ok": True, "action": "dismissed"}

    # accept → append to playbook
    if not body.answer or len(body.answer.strip()) < 5:
        raise HTTPException(400, "Provide an `answer` (min 5 chars) to add to the playbook")

    pb = await db.app_settings.find_one(
        {"id": "coach_playbook"}, {"_id": 0, "text": 1},
    )
    current = (pb or {}).get("text") or ""
    if not current:
        current = circle_dm_bot.DEFAULT_PLAYBOOK
    entry = f"\n\n- **{question.strip()}** {body.answer.strip()}"
    new_text = (current.rstrip() + entry).strip()[:8000]
    await db.app_settings.update_one(
        {"id": "coach_playbook"},
        {"$set": {
            "id": "coach_playbook",
            "text": new_text,
            "updated_at": now,
            "updated_by": user.get("id"),
            "updated_by_name": user.get("name") or user.get("email"),
        }},
        upsert=True,
    )
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {"circle_dm_meta.suggestion_status": "added",
                  "circle_dm_meta.suggestion_handled_at": now,
                  "updated_at": now}},
    )
    return {"ok": True, "action": "added", "playbook_chars": len(new_text)}
