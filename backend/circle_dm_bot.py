"""
Circle Community DM Bot — receives student DMs to coaches via Circle workflows,
generates an AI reply (or escalation), and creates a support ticket when the
team needs to step in.

Flow (configured in Circle UI):
  Student DMs a coach in Circle
  → Existing Circle Workflow "Admin received a direct message"
    Step 1: Webhook → POST /api/circle/dm-webhook with the DM payload
    Step 2: Send a Direct Message action → uses
            `{{ webhook.response.reply_text }}` from step 1's response
    Step 3 (conditional): If `{{ webhook.response.escalated }}` is true,
            we've already created a ticket + Slack-pinged Coralie.

The webhook RESPONDS synchronously (within 5s) so Circle's workflow can use
the AI-drafted text on the next step. Anything async (Slack pings, deep
ticket enrichment) happens in FastAPI's BackgroundTasks AFTER the response.

For sensitive topics (refund, complaint, urgent) we skip the resolve attempt
entirely and send a "passed to team" holding reply + create a ticket + Slack
DM Coralie.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Sensitive keywords that always escalate, no AI resolve attempt
ESCALATE_KEYWORDS = {
    "refund", "money back", "cancel", "complaint", "complain",
    "urgent", "emergency", "asap", "right now", "immediately",
    "lawyer", "legal", "unhappy", "disappointed", "angry", "furious",
    "scam", "fraud",
}

DEFAULT_PLAYBOOK = """\
# AYCI Coach Playbook
Use these answers for common questions. If the question is outside this list, hand it to the team.

- **How do I submit a private-tier video?** Use the Tally form linked in your Private Tier welcome email; videos are reviewed within 48h.
- **Where do I book a mock interview?** Check your Calendly invite or the booking link on the AYCI Academy "Welcome" space.
- **Can I reschedule my mock?** Yes, use the reschedule link in your Calendly confirmation email. If less than 24h notice, the call won't roll over.
- **I can't log in to AYCI Academy / Circle.** Try a password reset at app.circle.so. If still stuck, the team will fix it for you.
- **When is the next intake?** Check the AYCI Academy "Welcome" pinned post for the next cohort start date.
- **Refunds / cancellations / complaints**: Always escalate to the team. Never quote policy yourself.
"""


async def _get_playbook(db) -> str:
    doc = await db.app_settings.find_one({"id": "coach_playbook"}, {"_id": 0, "text": 1})
    return (doc or {}).get("text") or DEFAULT_PLAYBOOK


def _walk(payload: dict, keys: list[str]) -> Optional[str]:
    """Find the first non-empty value matching any of `keys`, searching the
    payload and one level of nested dicts. Returns the value as a string."""
    if not isinstance(payload, dict):
        return None
    for k in keys:
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # Walk one level deep so we catch `{data: {member: {name: "..."}}}` etc.
    for sub in payload.values():
        if isinstance(sub, dict):
            for k in keys:
                v = sub.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            # Two levels deep — Circle wraps things in {data: {member: {...}}}
            for sub2 in sub.values():
                if isinstance(sub2, dict):
                    for k in keys:
                        v = sub2.get(k)
                        if isinstance(v, str) and v.strip():
                            return v.strip()
    return None


def _extract_dm_fields(payload: dict) -> tuple[str, str, str, str]:
    """Pull (sender_name, sender_email, coach_name, message) from Circle's
    webhook payload regardless of shape. Returns sensible fallbacks if a field
    is missing."""

    def _get_in(d: dict, *paths: tuple[str, ...]) -> Optional[str]:
        for path in paths:
            cur = d
            for k in path:
                if isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                else:
                    cur = None
                    break
            if isinstance(cur, str) and cur.strip():
                return cur.strip()
        return None

    # Sender (the community member who DM'd)
    sender_name = _get_in(payload,
        ("sender_name",), ("from_name",), ("member_name",), ("full_name",),
        # Nested: any of these dict keys with a `name` field inside
        ("sender", "name"), ("from", "name"), ("member", "name"), ("user", "name"),
        ("data", "sender", "name"), ("data", "from", "name"),
        ("data", "member", "name"), ("data", "user", "name"),
    ) or _walk(payload, ["name", "first_name"]) or "there"

    sender_email = (_get_in(payload,
        ("sender_email",), ("from_email",), ("member_email",), ("email",),
        ("sender", "email"), ("from", "email"), ("member", "email"), ("user", "email"),
        ("data", "sender", "email"), ("data", "from", "email"),
        ("data", "member", "email"), ("data", "user", "email"),
    ) or "").lower()

    # Coach (the admin the DM was sent to)
    coach_name = _get_in(payload,
        ("coach_name",), ("admin_name",), ("recipient_name",), ("to_name",),
        ("admin", "name"), ("recipient", "name"), ("to", "name"),
        ("data", "admin", "name"), ("data", "recipient", "name"),
        ("data", "to", "name"),
    ) or "the team"

    # Message body
    message = _get_in(payload,
        ("message",), ("message_body",), ("body",), ("text",), ("content",),
        ("message", "body"), ("message", "text"), ("message", "content"),
        ("data", "message", "body"), ("data", "message", "text"),
        ("data", "message_body",), ("data", "body",),
    ) or _walk(payload, ["body", "text", "content"]) or ""

    return sender_name, sender_email, coach_name, message


def _is_sensitive(text: str) -> tuple[bool, Optional[str]]:
    """Return (escalate, reason). Hard escalation rules — no AI judgment."""
    if not text:
        return False, None
    low = text.lower()
    for kw in ESCALATE_KEYWORDS:
        if kw in low:
            return True, kw
    return False, None


async def _generate_reply(
    *, message: str, sender_name: str, coach_name: str, playbook: str,
) -> dict:
    """Ask Claude either:
      • For an AI resolve (if the playbook covers it, plain answer + sign with
        coach's name + AI disclosure)
      • Or to return the special token `NEEDS_HUMAN` so we escalate

    Returns {reply: str, resolved: bool}.
    """
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        # Fail open — if the LLM is down, escalate every DM rather than ignore.
        return {"reply": _holding_reply(sender_name, coach_name), "resolved": False}

    system = (
        "You are the auto-responder for AYCI Academy coaches' Circle DMs. "
        "A community member has DM'd a specific coach who isn't available to "
        "reply right now. You answer ONLY when the question is clearly answered "
        "by the COACH PLAYBOOK below. Otherwise, output exactly the token "
        "`NEEDS_HUMAN` and nothing else, and the team will pick it up.\n\n"
        f"=== COACH PLAYBOOK ===\n{playbook}\n=== END PLAYBOOK ===\n\n"
        "When you DO answer, write as if you ARE the coach. The student does NOT "
        "need to know the reply is automated — never mention that, never call "
        "yourself a bot, never use the phrase 'auto-response'. Be warm, friendly "
        "and encouraging — like a real coach who knows them well.\n\n"
        "Rules:\n"
        "1. If the playbook does not clearly cover the question, output `NEEDS_HUMAN`.\n"
        f"2. If you DO answer: start with 'Hi {sender_name}, ' followed by a warm "
        "opener (e.g. 'thanks for reaching out!', 'great question!', 'hope you're "
        "doing well!'). Then give the helpful answer in plain, conversational "
        "language. End with something supportive like 'Hope that helps!', "
        "'Let me know if you need anything else!', or 'Speak soon!'. Sign off "
        f"with just the coach's first name on a new line: '{(coach_name or '').split(' ')[0]} x'. "
        "Keep total reply under 600 characters.\n"
        "3. Never invent facts not in the playbook. Never quote refund or "
        "cancellation policy. Never reference dates, prices, or names that "
        "aren't in the playbook.\n"
        "4. If the message is just hello / a greeting / very short with no "
        "question, output `NEEDS_HUMAN`.\n"
        "5. Plain text only — no markdown, no headers."
    )

    chat = LlmChat(
        api_key=key,
        session_id=f"circle-dm-{uuid.uuid4().hex[:8]}",
        system_message=system,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")
    try:
        resp = await chat.send_message(UserMessage(text=message))
    except Exception as e:
        logger.warning(f"[circle-dm-bot] Claude call failed: {e}")
        return {"reply": _holding_reply(sender_name, coach_name), "resolved": False}

    draft = (resp or "").strip()
    if not draft or draft.upper().startswith("NEEDS_HUMAN"):
        return {"reply": _holding_reply(sender_name, coach_name), "resolved": False}
    if len(draft) > 600:
        draft = draft[:600].rsplit(" ", 1)[0] + "…"
    return {"reply": draft, "resolved": True}


def _holding_reply(sender_name: str, coach_name: str) -> str:
    student_first = (sender_name or "there").split(" ")[0]
    coach_first = (coach_name or "").split(" ")[0] or "the team"
    return (
        f"Hi {student_first}, thanks so much for getting in touch! 🙏 "
        f"I've got your message and I'll come back to you within 24 hours. "
        f"If it's really urgent, drop us a line at support@medicalinterviewprep.com "
        f"and we'll jump on it sooner.\n\n"
        f"Speak soon,\n{coach_first} x"
    )


# ---------------------------------------------------------- Ticket + Slack
async def _create_ticket_from_dm(
    db, *, sender_name: str, sender_email: Optional[str], coach_name: str,
    message: str, ai_reply: str, escalation_reason: Optional[str],
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    priority = "urgent" if escalation_reason else "normal"
    coralie = await db.users.find_one(
        {"email": "coralie@medicalinterviewprep.com"},
        {"_id": 0, "id": 1},
    ) or {}
    ticket_id = str(uuid.uuid4())
    description = (
        f"Student DM in Circle to {coach_name}.\n\n"
        f"Original message:\n{message}\n\n"
        f"Auto-response sent: {ai_reply}\n\n"
        + (f"Escalation reason: matched '{escalation_reason}'\n" if escalation_reason else "")
    )
    ticket = {
        "id": ticket_id,
        "student_name": sender_name,
        "student_email": (sender_email or "").lower().strip(),
        "subject": f"Circle DM to {coach_name}: {message[:60]}{'…' if len(message) > 60 else ''}",
        "description": description,
        "priority": priority,
        "category": "circle_dm",
        "source": "circle_dm",
        "assignee_id": coralie.get("id"),  # always Coralie for v1
        "status": "open",
        "notes": [],
        "created_at": now,
        "updated_at": now,
        "wati_last_inbound_at": None,
        "circle_dm_meta": {
            "coach_name": coach_name,
            "escalation_reason": escalation_reason,
            "ai_resolved": False,
            "original_message": message,
        },
    }
    await db.tickets.insert_one(ticket)
    return ticket_id


async def _slack_notify_coralie_urgent(db, *, sender_name, coach_name, message, ticket_id):
    try:
        import slack_dm
        public_base = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
        link = f"{public_base}/tickets" if public_base else "Open the Tickets board"
        text = (
            f":rotating_light: *Urgent Circle DM* — student messaged {coach_name}\n"
            f"*{sender_name}* — _{message[:200]}{'…' if len(message) > 200 else ''}_\n"
            f"Ticket auto-created (#{ticket_id[:8]}). {link}"
        )
        await slack_dm.dm_user(db, "coralie@medicalinterviewprep.com", text)
    except Exception as e:
        logger.warning(f"[circle-dm-bot] Slack notify failed: {e}")


# ---------------------------------------------------------- Public entry point
async def handle_dm_webhook(db, payload: dict, background) -> dict:
    """Process an incoming Circle DM webhook. Returns the JSON that the Circle
    Workflow's next step ("Send a direct message") will use via
    `{{ webhook.response.reply_text }}`.

    `background` is FastAPI's BackgroundTasks — anything that can wait
    until after the HTTP response (Slack pings, secondary writes) goes here.

    Circle's "Send to webhook" action sends a minimal payload by default:
        {
          "type": "community_member_sent_dm_to_admin",
          "data": {
            "community_id": ...,
            "admin_community_member_id": ...,
            "sender_community_member_id": ...
          }
        }
    No names, no email, no message body. So we:
      1. Look up both members via the Admin API for names/emails
      2. Try the Headless API (if CIRCLE_HEADLESS_TOKEN is set) for the
         message body. If that fails or isn't configured, we skip AI resolve
         and fall back to a holding reply + Coralie-routed ticket.
    """
    import circle_api

    sender_name, sender_email, coach_name, message = _extract_dm_fields(payload)

    # If the webhook used only IDs, hydrate names/emails from the Admin API.
    data = payload.get("data") if isinstance(payload.get("data"), dict) else None
    sender_id = (data or payload).get("sender_community_member_id") or (data or payload).get("sender_id")
    admin_id = (data or payload).get("admin_community_member_id") or (data or payload).get("admin_id")
    admin_email: Optional[str] = None
    if sender_id and (sender_name == "there" or not sender_email):
        m = await circle_api.fetch_member(sender_id)
        if m:
            sender_name = m["name"] or sender_name
            sender_email = m["email"] or sender_email
    if admin_id:
        m = await circle_api.fetch_member(admin_id)
        if m:
            if coach_name == "the team":
                coach_name = m["name"] or coach_name
            admin_email = m.get("email")

    # If we still don't have the message body, try Headless (requires
    # CIRCLE_HEADLESS_TOKEN + a valid admin email).
    if not message and sender_id and admin_email:
        body = await circle_api.fetch_latest_dm_message(db, admin_email, int(sender_id))
        if body:
            message = body
    if not message:
        # No body to act on — could be a Circle test fire (empty `data`), or
        # we couldn't reach the Headless API. Create a "team should pick this
        # up" ticket if we at least know who DM'd whom, otherwise just
        # acknowledge so Circle's workflow can proceed.
        if not (sender_id or admin_id):
            return {"reply_text": _holding_reply("there", coach_name),
                    "escalated": False, "ai_resolved": False, "ticket_id": None}
        reply = _holding_reply(sender_name.split(" ")[0], coach_name)
        ticket_id = await _create_ticket_from_dm(
            db, sender_name=sender_name, sender_email=sender_email,
            coach_name=coach_name,
            message=("(message body not available — open Circle to read)" if not message else message),
            ai_reply=reply, escalation_reason="no_message_body",
        )
        background.add_task(
            _slack_notify_coralie_urgent, db,
            sender_name=sender_name, coach_name=coach_name,
            message="(message body not available — open Circle to read)",
            ticket_id=ticket_id,
        )
        return {"reply_text": reply, "escalated": True, "ai_resolved": False,
                "ticket_id": ticket_id, "reason": "no_message_body"}

    # First-name only, for friendlier salutation
    first = sender_name.split(" ")[0]
    sensitive, reason = _is_sensitive(message)

    if sensitive:
        # Skip AI resolve — hold + ticket + Slack ping
        reply = _holding_reply(first, coach_name)
        ticket_id = await _create_ticket_from_dm(
            db, sender_name=sender_name, sender_email=sender_email,
            coach_name=coach_name, message=message, ai_reply=reply,
            escalation_reason=reason,
        )
        background.add_task(
            _slack_notify_coralie_urgent, db,
            sender_name=sender_name, coach_name=coach_name,
            message=message, ticket_id=ticket_id,
        )
        return {"reply_text": reply, "escalated": True, "ai_resolved": False,
                "ticket_id": ticket_id, "reason": reason}

    # Non-sensitive: try the AI resolve
    playbook = await _get_playbook(db)
    res = await _generate_reply(
        message=message, sender_name=first,
        coach_name=coach_name, playbook=playbook,
    )
    reply = res["reply"]
    resolved = res["resolved"]
    ticket_id = None
    if not resolved:
        ticket_id = await _create_ticket_from_dm(
            db, sender_name=sender_name, sender_email=sender_email,
            coach_name=coach_name, message=message, ai_reply=reply,
            escalation_reason=None,
        )
    else:
        # Even on resolve, log a low-priority ticket so the team has audit trail
        # of what the bot said on coaches' behalf. Tickets get auto-closed by
        # the existing Bulk Close flow when no follow-up arrives in 7 days.
        ticket_id = await _create_ticket_from_dm(
            db, sender_name=sender_name, sender_email=sender_email,
            coach_name=coach_name, message=message, ai_reply=reply,
            escalation_reason=None,
        )
        await db.tickets.update_one(
            {"id": ticket_id},
            {"$set": {"status": "resolved", "priority": "low",
                      "circle_dm_meta.ai_resolved": True}},
        )

    return {
        "reply_text": reply,
        "escalated": not resolved,
        "ai_resolved": resolved,
        "ticket_id": ticket_id,
    }
