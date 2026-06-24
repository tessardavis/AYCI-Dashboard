"""Inbound Calendly webhook + one-time admin registration.

Replaces the Zapier "Bonus Call Booked (Anoop's calendar)" zap — the action
logic lives in calendly_webhook.py. Calendly POSTs every org booking here; we
verify the signature, then act only on AYCI Bonus Call bookings.

Go-live (admin, once): POST /api/admin/calendly/register-webhook to create the
Calendly subscription and store its signing key. Inspect/clean up existing
subscriptions via GET /api/admin/calendly/webhooks.
"""
import logging
import os
import secrets

import httpx
from fastapi import APIRouter, Request, HTTPException, Depends

import calendly_webhook
import connectors
from db import db
from deps import require_admin

router = APIRouter(prefix="/api", tags=["calendly"])
logger = logging.getLogger(__name__)

_DEFAULT_CALLBACK = "https://ayci-dashboard.onrender.com/api/calendly/webhook"


@router.post("/calendly/webhook")
async def calendly_webhook_receiver(request: Request):
    """Receive a signed Calendly event. Always returns 200 once the signature
    is valid — a handler error is logged and swallowed so Calendly doesn't
    retry-storm on a bug we've already recorded."""
    raw = await request.body()
    sig = request.headers.get("Calendly-Webhook-Signature", "")
    key = await calendly_webhook._get_signing_key(db)
    if not calendly_webhook.verify_signature(raw, sig, key):
        raise HTTPException(401, "invalid Calendly signature")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "invalid JSON")

    if body.get("event") != "invitee.created":
        return {"ok": True, "skipped": body.get("event")}

    try:
        result = await calendly_webhook.handle_invitee_created(db, body.get("payload") or {})
        return {"ok": True, "result": result}
    except Exception as e:
        logger.exception("[calendly] handler error")
        return {"ok": False, "error": str(e)[:200]}


@router.post("/admin/calendly/register-webhook")
async def register_calendly_webhook(admin: dict = Depends(require_admin)):
    """Create the org-scoped Calendly webhook subscription that feeds
    /api/calendly/webhook, and store its signing key. Calendly rejects a
    duplicate (url, scope) — if recreating, delete the old one first
    (GET then DELETE via the Calendly UI, or extend this module)."""
    if not os.environ.get("CALENDLY_TOKEN"):
        raise HTTPException(400, "CALENDLY_TOKEN not set")
    callback = os.environ.get("CALENDLY_WEBHOOK_URL") or _DEFAULT_CALLBACK
    signing_key = secrets.token_hex(32)

    async with httpx.AsyncClient(timeout=30) as c:
        me = await c.get(f"{connectors.CALENDLY_BASE}/users/me",
                         headers=connectors._calendly_headers())
        me.raise_for_status()
        org = (me.json().get("resource") or {}).get("current_organization")
        if not org:
            raise HTTPException(400, "could not resolve Calendly organization")
        sub = await c.post(
            f"{connectors.CALENDLY_BASE}/webhook_subscriptions",
            headers={**connectors._calendly_headers(), "Content-Type": "application/json"},
            json={
                "url": callback,
                "events": ["invitee.created"],
                "organization": org,
                "scope": "organization",
                "signing_key": signing_key,
            },
        )
    if sub.status_code >= 300:
        raise HTTPException(sub.status_code, f"Calendly rejected: {sub.text[:300]}")

    resource = sub.json().get("resource", {})
    await db.app_settings.update_one(
        {"id": "calendly_webhook"},
        {"$set": {"id": "calendly_webhook", "signing_key": signing_key,
                  "callback": callback, "subscription_uri": resource.get("uri")}},
        upsert=True,
    )
    logger.info(f"[calendly] webhook registered: {resource.get('uri')} → {callback}")
    return {"ok": True, "callback": callback, "subscription": resource}


@router.get("/admin/calendly/webhooks")
async def list_calendly_webhooks(admin: dict = Depends(require_admin)):
    """List current org webhook subscriptions (diagnostic / cleanup)."""
    async with httpx.AsyncClient(timeout=30) as c:
        me = await c.get(f"{connectors.CALENDLY_BASE}/users/me",
                         headers=connectors._calendly_headers())
        me.raise_for_status()
        org = (me.json().get("resource") or {}).get("current_organization")
        r = await c.get(f"{connectors.CALENDLY_BASE}/webhook_subscriptions",
                        headers=connectors._calendly_headers(),
                        params={"organization": org, "scope": "organization"})
    return r.json()
