"""Wati WhatsApp Business — webhook + admin endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

import wati
from db import db
from deps import require_admin, require_board

router = APIRouter(prefix="/api/wati", tags=["wati"])


@router.get("/status")
async def status(admin: dict = Depends(require_admin)):
    return await wati.status()


@router.get("/recent")
async def recent_webhook_events(
    limit: int = 30,
    admin: dict = Depends(require_admin),
):
    """Return the last N raw Wati webhook events the server received, with the
    decision we made on each (ignored / duplicate / appended / created). Lets
    the admin self-diagnose missing replies without grep'ing logs."""
    rows = await db.wati_webhook_log.find(
        {}, {"_id": 0}
    ).sort("received_at", -1).to_list(min(max(limit, 1), 200))
    return {"events": rows}


@router.post("/webhook")
async def webhook(request: Request):
    """Public webhook endpoint Wati posts incoming messages to.

    Configure in Wati: Connectors → Webhooks → Add Webhook
    URL: https://<host>/api/wati/webhook
    Events: Message Received (and optionally Template Replied)
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")
    try:
        return await wati.handle_webhook(db, payload)
    except Exception as e:
        # Never 500 — Wati would aggressively retry. Log and ack.
        return {"action": "error", "error": str(e)}


@router.get("/templates")
async def templates(user: dict = Depends(require_board("tickets"))):
    return {"templates": await wati.list_templates()}


@router.post("/tickets/{ticket_id}/reply")
async def reply(
    ticket_id: str,
    payload: dict,
    user: dict = Depends(require_board("tickets")),
):
    """Send a free-text WhatsApp reply (within 24h session window)."""
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(400, "body required")
    if not wati.is_configured():
        raise HTTPException(400, "Wati not configured — admin must set WATI_BASE_URL + WATI_ACCESS_TOKEN")
    try:
        return await wati.send_session_message(db, ticket_id, body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@router.post("/tickets/{ticket_id}/template")
async def template(
    ticket_id: str,
    payload: dict,
    user: dict = Depends(require_board("tickets")),
):
    """Send a pre-approved template message (re-engagement after 24h)."""
    template_name = (payload.get("template_name") or "").strip()
    if not template_name:
        raise HTTPException(400, "template_name required")
    broadcast_name = (payload.get("broadcast_name") or template_name).strip()
    parameters = payload.get("parameters") or []
    if not isinstance(parameters, list):
        raise HTTPException(400, "parameters must be a list")
    try:
        return await wati.send_template_message(
            db, ticket_id,
            template_name=template_name,
            broadcast_name=broadcast_name,
            parameters=parameters,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
