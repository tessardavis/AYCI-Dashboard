"""
Gmail inbox auto-pull → Support Tickets.

Phase 2 of the Support Tickets feature. Connects multiple Gmail accounts via
per-inbox OAuth, polls each connected inbox every 15 min, and turns every new
inbound message into a Ticket (or appends to an existing ticket if it's a
reply on an existing thread).

Mongo collections:
- `gmail_inboxes`         — one doc per connected inbox (email, tokens, last sync)
- `gmail_oauth_states`    — short-lived OAuth state tokens (10 min TTL)

Env required:
- GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
- GMAIL_OAUTH_REDIRECT_URI = https://<host>/api/oauth/gmail/callback
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Any, Optional

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import tickets as tickets_mod

logger = logging.getLogger(__name__)


# Read + send. Send is required for two-way reply from the ticket detail.
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

OAUTH_STATE_TTL_MIN = 10
TOKEN_URI = "https://oauth2.googleapis.com/token"

# Inbound emails from these domains are TEAM mail, never tickets.
INTERNAL_DOMAINS = {"medicalinterviewprep.com", "aycimedical.com"}

# Auto-assignment: when an email lands in one of these inboxes, the new
# ticket is auto-assigned to the matching team member by NAME (we resolve
# the team_member_id at runtime so renames don't break us).
# Maps a SET of inbox local-parts (everything before @) → team member name.
INBOX_AUTO_ASSIGN = {
    frozenset({"tessa", "arub"}): "Arub Yousuf",
    frozenset({"oksana", "coralie"}): "Coralie Fairon",
}

# Cap per-inbox per-poll to avoid hammering the API on first sync.
MAX_MESSAGES_PER_POLL = 50


async def _resolve_assignee_for_inbox(db, inbox_email: str) -> Optional[str]:
    """Return team_member_id to auto-assign for tickets landing in this inbox.

    Reads the live mapping from `app_settings.inbox_routing` (admin-editable
    in Settings → Team) and resolves the team_member_id at run-time so renames
    don't break us. Falls back to the hardcoded `INBOX_AUTO_ASSIGN`."""
    if not inbox_email or "@" not in inbox_email:
        return None
    local = inbox_email.split("@", 1)[0].lower()

    target_name: Optional[str] = None
    try:
        import settings_store
        rules = await settings_store.get_inbox_routing(db)
        for rule in rules:
            if local in rule.get("inbox_locals", []):
                target_name = rule.get("team_member_name")
                break
    except Exception as e:
        logger.warning(f"[gmail] inbox routing lookup failed: {e}")

    if not target_name:
        for keys, name in INBOX_AUTO_ASSIGN.items():
            if local in keys:
                target_name = name
                break

    if not target_name:
        return None
    tm = await db.team_members.find_one({"name": target_name}, {"_id": 0, "id": 1})
    return tm.get("id") if tm else None


def _client_id() -> str:
    return os.environ.get("GOOGLE_CLIENT_ID", "")


def _client_secret() -> str:
    return os.environ.get("GOOGLE_CLIENT_SECRET", "")


def _redirect_uri() -> str:
    return os.environ.get(
        "GMAIL_OAUTH_REDIRECT_URI",
        "https://ayci-dashboard.preview.emergentagent.com/api/oauth/gmail/callback",
    )


def is_configured() -> bool:
    return bool(_client_id() and _client_secret())


def _flow() -> Flow:
    return Flow.from_client_config(
        {
            "web": {
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": TOKEN_URI,
            }
        },
        scopes=GMAIL_SCOPES,
        redirect_uri=_redirect_uri(),
    )


# -------------------------------------------------------- OAuth flow
async def start_oauth(
    db, *, user_id: str, ingest_inbound: bool = False, return_to: str = "/settings",
) -> str:
    """Generate an OAuth URL the user clicks to connect their Gmail account."""
    if not is_configured():
        raise RuntimeError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set")
    flow = _flow()
    url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",  # forces refresh_token issuance every time
        include_granted_scopes="true",
    )
    await db.gmail_oauth_states.insert_one({
        "state": state,
        "code_verifier": flow.code_verifier,  # PKCE — required to redeem the code
        "return_to": return_to,
        "user_id": user_id,
        "ingest_inbound": bool(ingest_inbound),
        "created_at": datetime.now(timezone.utc),
    })
    return url


async def complete_oauth(db, code: str, state: str) -> dict:
    """Exchange code for tokens and persist a connected inbox."""
    state_doc = await db.gmail_oauth_states.find_one({"state": state})
    if not state_doc:
        raise ValueError("Unknown or expired OAuth state")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=OAUTH_STATE_TTL_MIN)
    created = state_doc.get("created_at")
    if created and (created.tzinfo is None):
        created = created.replace(tzinfo=timezone.utc)
    if created and created < cutoff:
        await db.gmail_oauth_states.delete_one({"state": state})
        raise ValueError("OAuth state expired — try again")

    import warnings

    flow = _flow()
    # Restore the PKCE verifier from the start step — Google requires it to
    # exchange the auth code we just received for tokens.
    code_verifier = state_doc.get("code_verifier")
    if code_verifier:
        flow.code_verifier = code_verifier
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # scope-order warning
        flow.fetch_token(code=code)

    creds = flow.credentials
    if not creds.refresh_token:
        # Most common cause: user has previously granted access without prompt=consent
        raise ValueError(
            "Google didn't return a refresh token. Revoke previous access at "
            "https://myaccount.google.com/permissions and try again."
        )

    # Discover the email address that was authorised
    service = build("oauth2", "v2", credentials=creds, cache_discovery=False)
    info = service.userinfo().get().execute()
    email = (info.get("email") or "").lower().strip()
    if not email:
        raise ValueError("Could not read email address from Google account")

    expires_at = creds.expiry
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    inbox_doc = {
        "id": str(uuid.uuid4()),
        "email": email,
        "name": info.get("name") or email.split("@")[0],
        "user_id": state_doc.get("user_id"),
        "ingest_inbound": bool(state_doc.get("ingest_inbound")),
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "expires_at": expires_at,
        "scopes": list(creds.scopes or GMAIL_SCOPES),
        "last_sync_at": None,
        "last_sync_status": None,
        "last_message_at": None,  # date of newest message we've ingested
        "last_history_id": None,
        "connected_at": datetime.now(timezone.utc),
        "tickets_created": 0,
        "tickets_updated": 0,
    }

    # Upsert by email (re-connecting the same inbox refreshes tokens + owner)
    await db.gmail_inboxes.update_one(
        {"email": email},
        {"$set": {k: v for k, v in inbox_doc.items() if k not in ("id", "tickets_created", "tickets_updated")},
         "$setOnInsert": {"id": inbox_doc["id"], "tickets_created": 0, "tickets_updated": 0}},
        upsert=True,
    )
    await db.gmail_oauth_states.delete_one({"state": state})
    return {"email": email, "return_to": state_doc.get("return_to") or "/settings"}


async def list_inboxes(db, *, user_id: Optional[str] = None) -> list[dict]:
    """If user_id provided, filter to inboxes owned by that user. Admin should
    pass None to see all connected inboxes."""
    q: dict = {}
    if user_id is not None:
        q["user_id"] = user_id
    rows = await db.gmail_inboxes.find(
        q,
        {"_id": 0, "access_token": 0, "refresh_token": 0, "scopes": 0},
    ).sort("connected_at", 1).to_list(50)
    return rows


async def remove_inbox(db, inbox_id: str, *, user_id: Optional[str] = None) -> bool:
    """If user_id provided, only allow deletion by the owner."""
    q: dict = {"id": inbox_id}
    if user_id is not None:
        q["user_id"] = user_id
    res = await db.gmail_inboxes.delete_one(q)
    return res.deleted_count > 0


async def get_inbox_for_user(db, user_id: str) -> Optional[dict]:
    """Return the first connected inbox for this user — used as the default
    'From' when they reply to a ticket."""
    return await db.gmail_inboxes.find_one(
        {"user_id": user_id},
        {"_id": 0, "access_token": 0, "refresh_token": 0, "scopes": 0},
        sort=[("connected_at", 1)],
    )


# -------------------------------------------------------- Auth refresh
async def _build_service(db, inbox: dict):
    """Return a Gmail API service for the given inbox doc, refreshing the
    access token if needed."""
    creds = Credentials(
        token=inbox.get("access_token"),
        refresh_token=inbox.get("refresh_token"),
        token_uri=TOKEN_URI,
        client_id=_client_id(),
        client_secret=_client_secret(),
        scopes=inbox.get("scopes") or GMAIL_SCOPES,
    )
    expires = inbox.get("expires_at")
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if not expires or datetime.now(timezone.utc) >= expires - timedelta(minutes=1):
        # Refresh
        creds.refresh(GoogleRequest())
        await db.gmail_inboxes.update_one(
            {"id": inbox["id"]},
            {"$set": {
                "access_token": creds.token,
                "expires_at": creds.expiry.replace(tzinfo=timezone.utc) if creds.expiry and creds.expiry.tzinfo is None else creds.expiry,
            }},
        )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# -------------------------------------------------------- Message helpers
def _decode_b64url(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _walk_parts(part: dict, out: list[dict]) -> None:
    out.append(part)
    for sub in part.get("parts") or []:
        _walk_parts(sub, out)


def _extract_body(payload: dict) -> tuple[str, list[dict]]:
    """Return (plain_text_body, attachment_metadata).

    Attachment metadata: [{filename, size, mime_type, attachment_id}]. The
    `attachment_id` is the Gmail attachment id used to fetch bytes; we keep
    `size` so the caller can decide whether to download.
    """
    flat: list[dict] = []
    _walk_parts(payload or {}, flat)

    plain = ""
    html_fallback = ""
    attachments: list[dict] = []
    for p in flat:
        mime = p.get("mimeType") or ""
        body = p.get("body") or {}
        filename = p.get("filename") or ""
        if filename and (body.get("attachmentId") or body.get("size")):
            attachments.append({
                "filename": filename,
                "size": int(body.get("size") or 0),
                "mime_type": mime,
                "attachment_id": body.get("attachmentId"),
            })
            continue
        data = body.get("data")
        if not data:
            continue
        if mime == "text/plain" and not plain:
            plain = _decode_b64url(data)
        elif mime == "text/html" and not html_fallback:
            html_fallback = _decode_b64url(data)

    if not plain and html_fallback:
        # Strip tags very loosely — good enough for ticket previews
        import re
        plain = re.sub(r"<[^>]+>", " ", html_fallback)
        plain = re.sub(r"\s+", " ", plain).strip()
    return plain.strip(), attachments


async def _download_gmail_attachments(
    db, service, gmail_msg_id: str, attachments_meta: list[dict],
) -> list[dict]:
    """Pull each Gmail attachment's bytes and store in GridFS. Returns the
    list of attachment dicts to embed on the ticket."""
    import attachments as att_store
    out: list[dict] = []
    for meta in attachments_meta:
        att_id = meta.get("attachment_id")
        if not att_id:
            continue
        if (meta.get("size") or 0) > att_store.MAX_BYTES:
            continue
        try:
            res = service.users().messages().attachments().get(
                userId="me", messageId=gmail_msg_id, id=att_id,
            ).execute()
        except Exception as e:
            logger.warning(f"[gmail] attachment fetch failed {att_id}: {e}")
            continue
        data_b64 = res.get("data") or ""
        if not data_b64:
            continue
        try:
            raw = base64.urlsafe_b64decode(data_b64 + "=" * (-len(data_b64) % 4))
        except Exception:
            continue
        stored = await att_store.store_bytes(
            db, data=raw,
            filename=meta.get("filename") or "attachment",
            mime_type=meta.get("mime_type"),
            source="gmail",
        )
        if stored:
            out.append(stored)
    return out


def _header(headers: list[dict], name: str) -> str:
    n = name.lower()
    for h in headers or []:
        if (h.get("name") or "").lower() == n:
            return h.get("value") or ""
    return ""


def _is_internal(from_header: str) -> bool:
    """True if the sender's domain is one of our internal team domains."""
    _, addr = parseaddr(from_header or "")
    if "@" not in addr:
        return False
    domain = addr.split("@", 1)[1].lower().strip()
    return domain in INTERNAL_DOMAINS


# -------------------------------------------------------- Sync
async def sync_inbox(db, inbox: dict) -> dict:
    """Pull new inbound messages for one inbox and convert them to tickets.

    Returns {created, updated, scanned, errors}.
    """
    out = {"created": 0, "updated": 0, "scanned": 0, "errors": 0}
    try:
        service = await _build_service(db, inbox)
    except Exception as e:
        logger.warning(f"[gmail] {inbox.get('email')} build service failed: {e}")
        await db.gmail_inboxes.update_one(
            {"id": inbox["id"]},
            {"$set": {"last_sync_at": datetime.now(timezone.utc), "last_sync_status": f"auth_error: {e}"}},
        )
        out["errors"] += 1
        return out

    # Lookback window: 24h on first sync, 30d if previously synced (catch-up)
    last_msg_at = inbox.get("last_message_at")
    if last_msg_at:
        lookback_days = 7  # safety overlap
    else:
        lookback_days = 1
    q = f"in:inbox newer_than:{lookback_days}d"

    try:
        result = service.users().messages().list(
            userId="me", q=q, maxResults=MAX_MESSAGES_PER_POLL,
        ).execute()
    except HttpError as e:
        logger.warning(f"[gmail] {inbox.get('email')} list messages failed: {e}")
        await db.gmail_inboxes.update_one(
            {"id": inbox["id"]},
            {"$set": {"last_sync_at": datetime.now(timezone.utc), "last_sync_status": f"api_error: {e}"}},
        )
        out["errors"] += 1
        return out

    msgs = result.get("messages") or []
    out["scanned"] = len(msgs)
    newest_internal_date_ms = 0

    for stub in msgs:
        msg_id = stub.get("id")
        if not msg_id:
            continue
        # Idempotency: have we already ingested this message?
        existing = await db.tickets.find_one(
            {"$or": [
                {"gmail_message_id": msg_id},
                {"notes.gmail_message_id": msg_id},
            ]},
            {"_id": 1},
        )
        if existing:
            continue
        try:
            full = service.users().messages().get(
                userId="me", id=msg_id, format="full",
            ).execute()
        except HttpError as e:
            logger.warning(f"[gmail] fetch msg {msg_id} failed: {e}")
            out["errors"] += 1
            continue

        try:
            handled = await _handle_message(db, inbox, full, service)
        except Exception as e:
            logger.exception(f"[gmail] handle message {msg_id} crashed: {e}")
            out["errors"] += 1
            continue
        if handled == "created":
            out["created"] += 1
        elif handled == "updated":
            out["updated"] += 1
        try:
            internal_ms = int(full.get("internalDate") or 0)
            if internal_ms > newest_internal_date_ms:
                newest_internal_date_ms = internal_ms
        except (TypeError, ValueError):
            pass

    update: dict[str, Any] = {
        "last_sync_at": datetime.now(timezone.utc),
        "last_sync_status": "ok",
    }
    if newest_internal_date_ms > 0:
        update["last_message_at"] = datetime.fromtimestamp(
            newest_internal_date_ms / 1000, tz=timezone.utc,
        )
    if out["created"]:
        update["tickets_created"] = (inbox.get("tickets_created") or 0) + out["created"]
    if out["updated"]:
        update["tickets_updated"] = (inbox.get("tickets_updated") or 0) + out["updated"]
    await db.gmail_inboxes.update_one({"id": inbox["id"]}, {"$set": update})
    return out


async def _handle_message(db, inbox: dict, msg: dict, service) -> Optional[str]:
    """Convert one Gmail message into either a new ticket or a note on an
    existing ticket (matched by Gmail threadId). Returns 'created', 'updated',
    or None when skipped."""
    payload = msg.get("payload") or {}
    headers = payload.get("headers") or []
    from_h = _header(headers, "From")
    if _is_internal(from_h):
        return None  # internal team mail, ignore

    subject = _header(headers, "Subject") or "(no subject)"
    thread_id = msg.get("threadId")
    msg_id = msg.get("id")
    snippet = (msg.get("snippet") or "").strip()
    body_text, attachments_meta = _extract_body(payload)
    body_text = body_text or snippet

    # Download + store attachment bytes (skips files > MAX_BYTES silently)
    stored_attachments: list[dict] = []
    if attachments_meta:
        stored_attachments = await _download_gmail_attachments(
            db, service, msg_id, attachments_meta,
        )

    # Internal date
    try:
        internal_ms = int(msg.get("internalDate") or 0)
    except (TypeError, ValueError):
        internal_ms = 0
    iso = (
        datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc).isoformat()
        if internal_ms else datetime.now(timezone.utc).isoformat()
    )

    sender_name, sender_email = parseaddr(from_h)
    sender_email = (sender_email or "").lower().strip()
    sender_name = (sender_name or "").strip() or (sender_email.split("@")[0] if sender_email else "Unknown")

    # Match an existing ticket on the same Gmail thread — but only if it's
    # in a reopenable status (open / in_progress / waiting / resolved). A
    # reply on a `closed` ticket spawns a fresh one.
    REOPENABLE = ["open", "in_progress", "waiting", "resolved"]
    existing = await db.tickets.find_one(
        {
            "gmail_thread_id": thread_id,
            "source": "email",
            "status": {"$in": REOPENABLE},
        } if thread_id else {"_id": "__never__"},
        {"_id": 0, "id": 1, "notes": 1, "status": 1},
    )

    if existing:
        # Append to the existing ticket as a note (the actual reply text)
        note = {
            "id": str(uuid.uuid4()),
            "author_id": "_gmail",
            "author_name": f"{sender_name} <{sender_email}>",
            "body": (body_text or "(empty body)"),
            "created_at": iso,
            "internal": True,
            "gmail_message_id": msg_id,
            "attachments": stored_attachments,
        }
        push: dict = {"notes": note}
        if stored_attachments:
            push["attachments"] = {"$each": stored_attachments}
        await db.tickets.update_one(
            {"id": existing["id"]},
            {
                "$push": push,
                "$set": {
                    "updated_at": iso,
                    # Bump status back to open if the ticket was waiting on student
                    "status": "open",
                },
            },
        )
        return "updated"

    # Brand-new thread → create a new ticket
    short_subject = subject.strip()
    if len(short_subject) > 80:
        short_subject = short_subject[:77].rstrip() + "…"
    if not short_subject:
        short_subject = "Email support request"

    desc = body_text or "(empty body)"

    # Auto-assign by which inbox received the email
    auto_assignee = await _resolve_assignee_for_inbox(db, inbox.get("email") or "")

    ticket = {
        "id": str(uuid.uuid4()),
        "student_name": sender_name,
        "student_email": sender_email,
        "subject": short_subject,
        "description": desc,
        "status": "open",
        "priority": "medium",
        "category": "other",
        "assignee_id": auto_assignee,
        "source": "email",
        "source_ref": msg_id,
        "gmail_message_id": msg_id,
        "gmail_thread_id": thread_id,
        "gmail_inbox_email": inbox.get("email"),
        "created_at": iso,
        "updated_at": iso,
        "resolved_at": None,
        "notes": [],
        "attachments": stored_attachments,
        "slack_urgent_sent": False,
    }
    await db.tickets.insert_one(ticket)
    # Email tickets default to medium → no Slack on creation; if a coach
    # bumps to Urgent later, the regular escalation path will fire Slack.
    return "created"


async def sync_all(db) -> dict:
    """Iterate every connected inbox flagged `ingest_inbound` and sync."""
    if not is_configured():
        return {"skipped": "not_configured"}
    inboxes = await db.gmail_inboxes.find({"ingest_inbound": True}, {"_id": 0}).to_list(50)
    totals = {"inboxes": len(inboxes), "created": 0, "updated": 0, "scanned": 0, "errors": 0}
    for inb in inboxes:
        try:
            r = await sync_inbox(db, inb)
            for k in ("created", "updated", "scanned", "errors"):
                totals[k] += r.get(k, 0)
        except Exception as e:
            logger.exception(f"[gmail] sync_all crashed on {inb.get('email')}: {e}")
            totals["errors"] += 1
    return totals


# -------------------------------------------------------- Outbound (reply)
import base64 as _b64  # noqa: E402
from email.mime.text import MIMEText  # noqa: E402
from email.utils import formataddr, make_msgid  # noqa: E402


async def send_reply(
    db,
    ticket: dict,
    body: str,
    *,
    from_inbox_email: Optional[str] = None,
    sender_user_id: Optional[str] = None,
) -> dict:
    """Send an email reply to any ticket that has a student email.

    Inbox preference (first non-None wins):
      1. `from_inbox_email` (explicit pick)
      2. `ticket.gmail_inbox_email` (original inbox that received it — email source)
      3. the inbox owned by `sender_user_id` (the current user's personal Gmail)
      4. the first connected inbox globally (fallback)

    The send is logged as a note on the ticket.
    """
    if not is_configured():
        raise RuntimeError("Gmail not configured")
    recipient = (ticket.get("student_email") or "").strip()
    if not recipient:
        raise ValueError("Ticket has no student_email to reply to")

    original_inbox = ticket.get("gmail_inbox_email")
    target_inbox_email = from_inbox_email or original_inbox
    if not target_inbox_email and sender_user_id:
        own = await get_inbox_for_user(db, sender_user_id)
        if own:
            target_inbox_email = own["email"]
    if not target_inbox_email:
        # Last-resort fallback: first connected inbox
        first = await db.gmail_inboxes.find_one(
            {}, {"_id": 0, "email": 1}, sort=[("connected_at", 1)],
        )
        if not first:
            raise ValueError("No Gmail inbox connected — connect one first")
        target_inbox_email = first["email"]

    inbox = await db.gmail_inboxes.find_one({"email": target_inbox_email})
    if not inbox:
        raise ValueError(f"Inbox {target_inbox_email} no longer connected")

    service = await _build_service(db, inbox)

    # Threading: only for email-sourced tickets replying via the original inbox
    in_reply_to = ""
    references = ""
    thread_id = ticket.get("gmail_thread_id") if target_inbox_email == original_inbox else None
    original_subject = (ticket.get("subject") or "").strip() or "(no subject)"
    if thread_id:
        try:
            t = service.users().threads().get(
                userId="me", id=thread_id, format="metadata",
                metadataHeaders=["Message-ID", "References", "Subject"],
            ).execute()
            messages = t.get("messages") or []
            if messages:
                msg = messages[-1]
                headers = msg.get("payload", {}).get("headers") or []
                in_reply_to = _header(headers, "Message-ID")
                references = _header(headers, "References") or in_reply_to
                sub = _header(headers, "Subject")
                if sub:
                    original_subject = sub
        except HttpError as e:
            logger.warning(f"[gmail] reply thread fetch failed: {e}")
            thread_id = None  # fall back to fresh thread

    subject = original_subject
    if thread_id and not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    mime = MIMEText(body, "plain", "utf-8")
    mime["To"] = recipient
    mime["From"] = formataddr((inbox.get("name") or "Support", target_inbox_email))
    mime["Subject"] = subject
    mime["Message-ID"] = make_msgid(domain=target_inbox_email.split("@", 1)[-1])
    if in_reply_to:
        mime["In-Reply-To"] = in_reply_to
        mime["References"] = (references + " " + in_reply_to).strip()

    raw = _b64.urlsafe_b64encode(mime.as_bytes()).decode()
    send_body: dict = {"raw": raw}
    if thread_id:
        send_body["threadId"] = thread_id
    try:
        sent = service.users().messages().send(
            userId="me", body=send_body,
        ).execute()
    except HttpError as e:
        raise RuntimeError(f"Gmail send failed: {e}")

    # Log as a note on the ticket. If this is the first reply for a non-email
    # ticket, also stash the new thread id so subsequent replies thread cleanly.
    iso = datetime.now(timezone.utc).isoformat()
    note = {
        "id": str(uuid.uuid4()),
        "author_id": "_gmail_outbound",
        "author_name": f"Reply via {target_inbox_email}",
        "body": body,
        "created_at": iso,
        "internal": True,
        "gmail_message_id": sent.get("id"),
    }
    update: dict = {"updated_at": iso}
    if not ticket.get("gmail_thread_id") and sent.get("threadId"):
        update["gmail_thread_id"] = sent.get("threadId")
        update["gmail_inbox_email"] = target_inbox_email
    await db.tickets.update_one(
        {"id": ticket["id"]},
        {"$push": {"notes": note}, "$set": update},
    )
    return {"ok": True, "gmail_message_id": sent.get("id"), "from_inbox": target_inbox_email}


def _header(headers: list[dict], name: str) -> str:  # noqa: F811 — re-exported
    n = name.lower()
    for h in headers or []:
        if (h.get("name") or "").lower() == n:
            return h.get("value") or ""
    return ""

