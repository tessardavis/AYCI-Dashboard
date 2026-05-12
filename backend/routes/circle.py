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
from deps import require_admin

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
async def get_coach_playbook(admin: dict = Depends(require_admin)):
    doc = await db.app_settings.find_one({"id": "coach_playbook"}, {"_id": 0, "text": 1, "updated_at": 1, "updated_by_name": 1})
    return {
        "text": (doc or {}).get("text") or circle_dm_bot.DEFAULT_PLAYBOOK,
        "is_default": not doc,
        "updated_at": (doc or {}).get("updated_at"),
        "updated_by_name": (doc or {}).get("updated_by_name"),
    }


@router.put("/coach-playbook")
async def update_coach_playbook(
    body: PlaybookUpdate, admin: dict = Depends(require_admin),
):
    await db.app_settings.update_one(
        {"id": "coach_playbook"},
        {"$set": {
            "id": "coach_playbook",
            "text": body.text.strip(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by_name": admin.get("name"),
        }},
        upsert=True,
    )
    return {"ok": True}


# --- Recent DM events (admin debug view) ------------------------------------
@router.get("/dm-events")
async def list_dm_events(admin: dict = Depends(require_admin), limit: int = 30):
    """Last N raw webhook payloads we received from Circle. Useful for
    debugging the Workflow setup and seeing exactly what Circle sends us."""
    rows = await db.circle_dm_events.find(
        {}, {"_id": 0},
    ).sort("received_at", -1).limit(min(max(1, limit), 100)).to_list(100)
    return {"events": rows}
