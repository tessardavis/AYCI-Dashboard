"""
Wati WhatsApp Business → Support Tickets.

Wati is a third-party WhatsApp BSP (https://wati.io) the team already uses.
This module:

- Receives incoming-message webhooks from Wati and converts them to tickets
  (or appends to an existing open ticket from the same WhatsApp number).
- Sends outbound replies from the ticket detail panel via the Wati REST API.
- Surfaces approved templates so coaches can re-engage students after the
  WhatsApp 24h conversation window has expired.

Threading rule (per spec):
- One OPEN ticket per WhatsApp number at a time. A new inbound message:
  - appends to the existing open ticket if one exists for that number
  - else creates a new ticket
- If the previous ticket was resolved/closed, a new one is created.

Env required:
- WATI_BASE_URL       e.g. https://live-mt-server.wati.io/12345
- WATI_ACCESS_TOKEN   bearer token (no "Bearer " prefix)
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

OPEN_STATUSES = {"open", "in_progress", "waiting"}


def _base_url() -> str:
    return (os.environ.get("WATI_BASE_URL") or "").rstrip("/")


def _token() -> str:
    return os.environ.get("WATI_ACCESS_TOKEN") or ""


def _phone() -> str:
    return os.environ.get("WATI_PHONE_NUMBER") or ""


def is_configured() -> bool:
    return bool(_base_url() and _token())


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise_phone(raw: str) -> str:
    """Strip everything but digits — Wati uses E.164 minus the leading +."""
    if not raw:
        return ""
    return "".join(ch for ch in str(raw) if ch.isdigit())


# -------------------------------------------------------- Auto-assignment
# Routing rules per AYCI:
#   - Prospect (not yet an Academy member) → Arub (sales/onboarding)
#   - Existing student asking about an upgrade/tier change → Arub
#   - Existing student with a general question → Coralie
UPGRADE_KEYWORDS = (
    "upgrade", "premium", "platinum", "gold tier", "silver tier",
    "tier", "1-1", "1:1", "one to one", "one-to-one", "one on one",
    "private coaching", "private coach", "individual coaching",
    "additional support", "more support",
)


def _looks_like_upgrade(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(kw in t for kw in UPGRADE_KEYWORDS)


async def _team_id_by_name(db, *names: str) -> Optional[str]:
    """Return the team_member.id whose name starts with any of `names`
    (case-insensitive). Used to resolve "Arub"/"Coralie" → uuid without
    hardcoding ids."""
    for name in names:
        if not name:
            continue
        m = await db.team_members.find_one(
            {"name": {"$regex": f"^{name}", "$options": "i"}},
            {"_id": 0, "id": 1},
        )
        if m:
            return m["id"]
    return None


async def resolve_whatsapp_assignee(db, *, wa_id: str, body: str) -> Optional[str]:
    """Pick the right team member for an inbound WhatsApp ticket based on
    sender status (existing student vs prospect) and message intent."""
    arub_id = await _team_id_by_name(db, "Arub")
    coralie_id = await _team_id_by_name(db, "Coralie")

    is_existing = False
    try:
        import student_match as sm
        match = await sm.match_student(phone=wa_id)
        is_existing = bool(match.get("matched"))
    except Exception as e:
        logger.warning(f"[wati] auto-assign student-match failed: {e}")

    if not is_existing:
        # Prospect → Arub
        return arub_id
    if _looks_like_upgrade(body):
        return arub_id
    return coralie_id or arub_id


# -------------------------------------------------------- Media download
async def _fetch_wati_media(
    db, media_id: str, *, filename: Optional[str], mime: Optional[str], msg_type: str,
) -> Optional[dict]:
    """Download a Wati-hosted media attachment and store in GridFS."""
    if not is_configured():
        return None
    import attachments as att_store
    # Wati exposes media via /api/v1/getMedia?fileName={mediaId}
    url = f"{_base_url()}/api/v1/getMedia"
    fname = filename or f"{msg_type}-{media_id}"
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as c:
            async with c.stream(
                "GET", url, headers={"Authorization": f"Bearer {_token()}"},
                params={"fileName": media_id},
            ) as r:
                if r.status_code >= 300:
                    logger.warning(f"[wati] media {media_id} returned {r.status_code}")
                    return None
                ctype = (
                    mime
                    or r.headers.get("content-type", "").split(";")[0].strip()
                    or None
                )
                # Add an extension if filename is missing one
                if "." not in fname.split("/")[-1]:
                    import mimetypes
                    ext = mimetypes.guess_extension(ctype or "") or ""
                    fname = fname + ext
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > att_store.MAX_BYTES:
                        logger.info(f"[wati] media {media_id} > {att_store.MAX_BYTES}, skipping")
                        return None
                return await att_store.store_bytes(
                    db, data=bytes(buf), filename=fname,
                    mime_type=ctype, source="whatsapp",
                )
    except Exception as e:
        logger.warning(f"[wati] media {media_id} fetch failed: {e}")
        return None


# -------------------------------------------------------- Webhook handling
async def handle_webhook(db, payload: dict) -> dict:
    """Process a single Wati webhook event. Returns {action, ticket_id|None}.

    Every decision is logged at INFO level so we can debug missing replies via
    the production logs (look for "[wati]" lines).
    """
    event = (payload.get("eventType") or payload.get("event_type") or "").strip()
    raw_wa = payload.get("waId") or payload.get("wa_id") or ""
    raw_msg_id = payload.get("id") or payload.get("messageId") or payload.get("whatsappMessageId")

    # Persist a slim trail of the last 200 webhook events so we can self-debug
    # without grep'ing production logs. Stored under the cache collection.
    try:
        await db.wati_webhook_log.insert_one({
            "received_at": _now_iso(),
            "event": event,
            "wa_id": raw_wa,
            "message_id": raw_msg_id,
            "owner": payload.get("owner"),
            "type": payload.get("type"),
            "text_preview": (payload.get("text") or payload.get("body") or "")[:200],
            "operator_email": payload.get("operatorEmail"),
            "raw_keys": sorted(list(payload.keys()))[:30],
        })
    except Exception:
        pass

    # Only act on inbound user messages. Wati's terminology varies by version
    # — accept all known received-from-customer variants. We deliberately
    # IGNORE other events (sessionMessageSent, statusUpdate, etc.) but log them.
    inbound_events = {
        "message", "messageReceived", "messageReceived_v2",
        "newMessageReceived", "messageNew", "incoming_message",
    }
    if event not in inbound_events:
        logger.info(f"[wati] ignored event={event!r} wa={raw_wa} msg_id={raw_msg_id}")
        return {"action": "ignored", "reason": f"event {event} not subscribed"}

    # In Wati's payload the message is at top level; body fields documented at
    # https://docs.wati.io/reference/message-received
    text = (payload.get("text") or payload.get("body") or "").strip()
    msg_type = (payload.get("type") or "text").lower()
    wa_id = _normalise_phone(raw_wa)
    sender_name = (payload.get("senderName") or payload.get("contactName") or "").strip()
    msg_id = raw_msg_id
    timestamp = payload.get("timestamp") or payload.get("created")
    operator_email = (payload.get("operatorEmail") or "").strip()

    # Media metadata — Wati flat payloads include these keys when type != text
    media_id = (
        payload.get("mediaId") or payload.get("media_id")
        or (payload.get("data") or {}).get("id") if isinstance(payload.get("data"), dict) else None
    )
    media_mime = (
        payload.get("mimeType") or payload.get("mime_type")
        or (payload.get("data") or {}).get("mime_type") if isinstance(payload.get("data"), dict) else None
    )
    media_filename = (
        payload.get("fileName") or payload.get("filename")
        or (payload.get("data") or {}).get("filename") if isinstance(payload.get("data"), dict) else None
    )
    media_caption = (
        payload.get("caption")
        or (payload.get("data") or {}).get("caption") if isinstance(payload.get("data"), dict) else None
    )

    if not wa_id:
        logger.warning(f"[wati] ignored event={event!r} reason=no_waId payload_keys={list(payload.keys())[:15]}")
        return {"action": "ignored", "reason": "no waId"}
    if not msg_id:
        # Wati sometimes omits id on test events; synthesise one
        msg_id = f"wati-{wa_id}-{int(datetime.now(timezone.utc).timestamp())}"

    # Idempotency: have we already ingested this message?
    dup = await db.tickets.find_one(
        {"$or": [
            {"wati_message_ids": msg_id},
            {"notes.wati_message_id": msg_id},
        ]},
        {"_id": 1},
    )
    if dup:
        logger.info(f"[wati] duplicate event={event!r} wa={wa_id} msg_id={msg_id}")
        return {"action": "duplicate", "message_id": msg_id}

    # Ignore outbound (operator) events that some Wati setups also fire as
    # `message` — these have an operatorEmail and `owner=true`.
    owner_flag = payload.get("owner")
    if owner_flag is True or (owner_flag == "true") or operator_email:
        logger.info(f"[wati] ignored outbound wa={wa_id} owner={owner_flag} operator={operator_email}")
        return {"action": "ignored", "reason": "outbound event"}

    iso = _now_iso()
    if timestamp:
        try:
            ts_int = int(timestamp)
            iso = datetime.fromtimestamp(ts_int, tz=timezone.utc).isoformat()
        except (TypeError, ValueError):
            pass

    body_text = text or media_caption or f"[{msg_type} message — no text body]"

    # Download media to GridFS if present
    stored_attachments: list[dict] = []
    if media_id and msg_type in {"image", "document", "audio", "video", "voice", "sticker"}:
        att = await _fetch_wati_media(db, media_id, filename=media_filename, mime=media_mime, msg_type=msg_type)
        if att:
            stored_attachments = [att]

    # Find an existing open ticket for this WhatsApp number
    existing = await db.tickets.find_one(
        {
            "source": "whatsapp",
            "wati_wa_id": wa_id,
            "status": {"$in": list(OPEN_STATUSES)},
        },
        {"_id": 0, "id": 1},
    )

    if existing:
        note = {
            "id": str(uuid.uuid4()),
            "author_id": "_whatsapp",
            "author_name": f"{sender_name or wa_id} (WhatsApp)",
            "body": body_text,
            "created_at": iso,
            "internal": True,
            "wati_message_id": msg_id,
            "attachments": stored_attachments,
        }
        push: dict = {"notes": note, "wati_message_ids": msg_id}
        if stored_attachments:
            push["attachments"] = {"$each": stored_attachments}
        await db.tickets.update_one(
            {"id": existing["id"]},
            {
                "$push": push,
                "$set": {"updated_at": iso, "status": "open"},
            },
        )
        logger.info(f"[wati] appended note ticket={existing['id']} wa={wa_id} msg_id={msg_id}")
        return {"action": "appended", "ticket_id": existing["id"]}

    # Brand-new ticket
    short_subject = body_text.replace("\n", " ").strip()
    if len(short_subject) > 80:
        short_subject = short_subject[:77].rstrip() + "…"
    if not short_subject:
        short_subject = "WhatsApp support request"

    # Pick assignee based on AYCI routing rules (prospect/upgrade → Arub,
    # existing student general question → Coralie).
    try:
        assignee_id = await resolve_whatsapp_assignee(db, wa_id=wa_id, body=body_text)
    except Exception as e:
        logger.warning(f"[wati] resolve assignee failed: {e}")
        assignee_id = None

    ticket = {
        "id": str(uuid.uuid4()),
        "student_name": sender_name or wa_id,
        "student_email": "",  # Wati doesn't provide email — surface waId instead
        "subject": short_subject,
        "description": body_text,
        "status": "open",
        "priority": "medium",
        "category": "other",
        "assignee_id": assignee_id,
        "source": "whatsapp",
        "source_ref": msg_id,
        "wati_wa_id": wa_id,
        "wati_sender_name": sender_name,
        "wati_message_ids": [msg_id],
        "wati_last_inbound_at": iso,
        "created_at": iso,
        "updated_at": iso,
        "resolved_at": None,
        "notes": [],
        "attachments": stored_attachments,
        "slack_urgent_sent": False,
    }
    await db.tickets.insert_one(ticket)
    logger.info(f"[wati] created ticket={ticket['id']} wa={wa_id} msg_id={msg_id} assigned_to={assignee_id}")
    return {"action": "created", "ticket_id": ticket["id"]}


# -------------------------------------------------------- Outbound
async def send_session_message(db, ticket_id: str, body: str) -> dict:
    """Send a free-text reply within the 24h WhatsApp session window. Wati's
    endpoint: POST /api/v1/sendSessionMessage/{whatsappNumber}?messageText=..."""
    if not is_configured():
        raise RuntimeError("Wati not configured")
    ticket = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not ticket:
        raise ValueError("Ticket not found")
    if ticket.get("source") != "whatsapp":
        raise ValueError("Ticket isn't a WhatsApp ticket")
    wa = ticket.get("wati_wa_id")
    if not wa:
        raise ValueError("Missing WhatsApp number on ticket")

    url = f"{_base_url()}/api/v1/sendSessionMessage/{wa}"
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(url, headers=_headers(), params={"messageText": body})
    if r.status_code >= 300:
        raise RuntimeError(f"Wati send failed {r.status_code}: {r.text[:300]}")

    data = r.json() if r.content else {}
    return await _record_outbound(db, ticket_id, body, data, kind="text")


async def send_template_message(
    db, ticket_id: str, *, template_name: str, broadcast_name: str, parameters: list[dict]
) -> dict:
    """Send a pre-approved template (re-engagement after 24h window).
    Wati: POST /api/v1/sendTemplateMessage?whatsappNumber={wa}"""
    if not is_configured():
        raise RuntimeError("Wati not configured")
    ticket = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not ticket:
        raise ValueError("Ticket not found")
    wa = ticket.get("wati_wa_id")
    if not wa:
        raise ValueError("Missing WhatsApp number on ticket")

    url = f"{_base_url()}/api/v1/sendTemplateMessage"
    body = {
        "template_name": template_name,
        "broadcast_name": broadcast_name or template_name,
        "parameters": parameters or [],
    }
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(url, headers=_headers(), params={"whatsappNumber": wa}, json=body)
    if r.status_code >= 300:
        raise RuntimeError(f"Wati template send failed {r.status_code}: {r.text[:300]}")

    data = r.json() if r.content else {}
    summary = f"[Template: {template_name}]"
    return await _record_outbound(db, ticket_id, summary, data, kind="template")


async def _record_outbound(db, ticket_id: str, body: str, wati_response: dict, *, kind: str) -> dict:
    iso = _now_iso()
    note = {
        "id": str(uuid.uuid4()),
        "author_id": "_whatsapp_outbound",
        "author_name": f"WhatsApp reply ({kind})",
        "body": body,
        "created_at": iso,
        "internal": True,
        "wati_message_id": (wati_response or {}).get("messageId") or (wati_response or {}).get("id"),
    }
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$push": {"notes": note}, "$set": {"updated_at": iso}},
    )
    return {"ok": True, "wati_response": wati_response}


# -------------------------------------------------------- Templates
async def list_templates() -> list[dict]:
    """Return approved Wati templates so the UI can show them as a dropdown
    when the 24h window has expired."""
    if not is_configured():
        return []
    url = f"{_base_url()}/api/v1/getMessageTemplates"
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(url, headers=_headers(), params={"pageSize": 100, "pageNumber": 0})
    if r.status_code >= 300:
        logger.warning(f"[wati] list templates failed {r.status_code}: {r.text[:200]}")
        return []
    body = r.json() or {}
    items = body.get("messageTemplates") or body.get("data") or []
    out: list[dict] = []
    for t in items:
        if (t.get("status") or "").upper() not in {"APPROVED", "ACCEPTED"}:
            continue
        out.append({
            "name": t.get("elementName") or t.get("name"),
            "language": t.get("language") or t.get("languageCode"),
            "category": t.get("category"),
            "body": t.get("body") or t.get("text") or "",
        })
    return out


# -------------------------------------------------------- Status
async def status() -> dict:
    return {
        "configured": is_configured(),
        "base_url": _base_url(),
        "phone": _phone(),
    }


# -------------------------------------------------------- Reconciliation
# Safety net: poll Wati for the latest inbound messages on every OPEN ticket
# and append any we don't already have. Catches webhook drops + URL-config
# drift (the exact bug that hid Shailaja's "Thanks" reply on 2026-05-05).
async def reconcile_open_tickets(db) -> dict:
    if not is_configured():
        return {"ok": False, "reason": "wati not configured"}
    tickets = await db.tickets.find(
        {"source": "whatsapp", "status": {"$in": list(OPEN_STATUSES)}},
        {"_id": 0, "id": 1, "wati_wa_id": 1, "student_name": 1, "wati_message_ids": 1},
    ).to_list(500)
    appended = 0
    scanned = 0
    errors: list[str] = []
    base = _base_url()
    headers = _headers()
    async with httpx.AsyncClient(timeout=20) as client:
        for t in tickets:
            wa = (t.get("wati_wa_id") or "").strip()
            if not wa:
                continue
            scanned += 1
            try:
                r = await client.get(
                    f"{base}/api/v1/getMessages/{wa}",
                    headers=headers,
                    params={"pageSize": 30},
                )
                if r.status_code >= 300:
                    errors.append(f"{wa}: HTTP {r.status_code}")
                    continue
                data = r.json() or {}
                msgs_raw = data.get("messages") or {}
                items = (
                    msgs_raw.get("items")
                    if isinstance(msgs_raw, dict)
                    else (msgs_raw or data.get("items") or [])
                ) or []
            except Exception as e:
                errors.append(f"{wa}: {e}")
                continue

            seen_ids = set(t.get("wati_message_ids") or [])
            # Also check note-level message ids to be safe
            ticket_full = await db.tickets.find_one(
                {"id": t["id"]}, {"_id": 0, "notes.wati_message_id": 1},
            )
            for n in (ticket_full or {}).get("notes", []) or []:
                if n.get("wati_message_id"):
                    seen_ids.add(n["wati_message_id"])

            for m in items:
                if m.get("owner") is True or m.get("owner") == "true":
                    continue  # outbound (operator) — already recorded when we sent it
                # Only text + named media. Skip status-update sentinels (type 0/1, no text).
                mtype = (m.get("type") or "").lower() if isinstance(m.get("type"), str) else None
                text = (m.get("text") or "").strip()
                if not text and mtype not in {"image", "document", "audio", "video", "voice"}:
                    continue
                mid = m.get("id") or m.get("messageId") or m.get("whatsappMessageId")
                if not mid or mid in seen_ids:
                    continue
                # Append as a note + record the message id
                created = m.get("created") or m.get("timestamp") or _now_iso()
                if isinstance(created, (int, float)):
                    try:
                        created = datetime.fromtimestamp(int(created), tz=timezone.utc).isoformat()
                    except Exception:
                        created = _now_iso()
                note = {
                    "id": str(uuid.uuid4()),
                    "author_id": "_whatsapp",
                    "author_name": f"{t.get('student_name') or wa} (WhatsApp · reconciled)",
                    "body": text or f"[{mtype} message — fetched via reconcile]",
                    "created_at": str(created),
                    "internal": True,
                    "wati_message_id": mid,
                    "attachments": [],
                }
                await db.tickets.update_one(
                    {"id": t["id"]},
                    {
                        "$push": {"notes": note, "wati_message_ids": mid},
                        "$set": {
                            "updated_at": _now_iso(),
                            "status": "open",
                            "wati_last_inbound_at": str(created),
                        },
                    },
                )
                appended += 1
                seen_ids.add(mid)
                logger.info(f"[wati-reconcile] appended ticket={t['id']} wa={wa} msg_id={mid}")
    return {"ok": True, "scanned": scanned, "appended": appended, "errors": errors[:10]}
