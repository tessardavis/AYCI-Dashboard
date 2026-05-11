"""
AI Ticket Triage — Claude-drafted reply suggestions for support tickets.

Behaviour:
  • Reads the ticket subject, description, full ordered conversation thread
    (inbound + team replies), and student tier/source (email / whatsapp).
  • Asks Claude Sonnet 4.5 for a short professional reply DRAFT that the
    coach edits before sending. We never auto-send.
  • Output is plain text (no markdown), tone-matched to AYCI's voice, and
    sized for the channel (long for email, ≤500 chars for WhatsApp).

The endpoint returns `{"draft": "..."}` synchronously. Cost is low because
each ticket is ~3-15 messages. The frontend just drops the result into the
existing reply textarea.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

WHATSAPP_CHAR_LIMIT = 500
EMAIL_CHAR_LIMIT = 1800


def _author_role(note: dict, ticket: dict) -> str:
    """Return 'student' / 'team' / 'system' for a single note."""
    aid = (note.get("author_id") or "").lower()
    if aid in {"_email", "_whatsapp", "_tally"}:
        return "student"
    if aid in {"_system", "_assignment", "_status"}:
        return "system"
    return "team"


def _build_thread(ticket: dict) -> list[dict]:
    """Reconstruct the conversation thread, oldest first."""
    rows: list[dict] = []
    # Opening message lives in `description` for Tally/WhatsApp tickets,
    # and may also be the initial email body.
    if ticket.get("description"):
        rows.append({
            "role": "student",
            "at": ticket.get("created_at"),
            "name": ticket.get("student_name") or ticket.get("requester_name") or "Student",
            "body": ticket["description"],
        })
    for n in (ticket.get("notes") or []):
        role = _author_role(n, ticket)
        if role == "system":
            continue
        rows.append({
            "role": role,
            "at": n.get("created_at"),
            "name": n.get("author_name") or ("Student" if role == "student" else "Team"),
            "body": (n.get("body") or "").strip(),
        })
    rows.sort(key=lambda r: r.get("at") or "")
    return [r for r in rows if r.get("body")]


def _format_thread_for_prompt(thread: list[dict]) -> str:
    out = []
    for r in thread:
        # Clip noisy email signatures / quote-blocks to keep tokens small.
        body = r["body"]
        # Trim quoted reply chains (lines starting with ">").
        lines = []
        for ln in body.splitlines():
            if ln.lstrip().startswith(">"):
                break
            lines.append(ln)
        clipped = "\n".join(lines).strip()
        if not clipped:
            clipped = body[:600]
        clipped = clipped[:1200]  # hard cap per message
        out.append(f"[{r['role'].upper()} · {r['name']}]\n{clipped}")
    return "\n\n".join(out)


def _system_prompt(channel: str) -> str:
    if channel == "whatsapp":
        return (
            "You are a support assistant at AYCI Academy (medical-interview prep). "
            "Draft a SHORT WhatsApp reply for the coach to send to a student. "
            f"Plain text only, no markdown, no greetings like 'Hi NAME,'. "
            f"Keep it under {WHATSAPP_CHAR_LIMIT} characters. "
            "Be warm, direct, helpful. Address the student's most recent question "
            "or concern. If the conversation needs a human decision (refund, "
            "policy exception, complaint), draft a holding reply that acknowledges "
            "and says the team will get back ASAP. Never invent details — if a "
            "fact isn't in the thread, don't reference it. Output the message body only."
        )
    # Email default
    return (
        "You are a support assistant at AYCI Academy (medical-interview prep). "
        "Draft a professional email REPLY for the coach to send to a student. "
        "Plain text only, no markdown, no email subject. Start directly with the "
        "greeting (e.g. 'Hi <first name>,'). Keep paragraphs short. End with a "
        f"warm sign-off ('Best, AYCI Team' or similar). Stay under {EMAIL_CHAR_LIMIT} characters. "
        "Address the student's most recent question or concern from the thread. "
        "If the conversation needs a human decision (refund, policy exception, "
        "complaint), draft a holding reply that acknowledges and says the team "
        "will get back ASAP. Never invent details — if a fact isn't in the "
        "thread, don't reference it. Output the message body only."
    )


def _channel_for(ticket: dict) -> str:
    src = (ticket.get("source") or "").lower()
    if src == "whatsapp":
        return "whatsapp"
    return "email"


async def suggest_reply_for_ticket(ticket: dict) -> dict:
    """Return {"draft": str, "channel": str, "thread_size": int}. Raises
    ValueError if the LLM key is missing or the ticket has no usable
    inbound content yet."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        raise ValueError("EMERGENT_LLM_KEY not configured")

    thread = _build_thread(ticket)
    has_student_msg = any(r["role"] == "student" for r in thread)
    if not has_student_msg:
        raise ValueError("No student messages on this ticket yet — nothing to reply to.")

    channel = _channel_for(ticket)
    student_name = ticket.get("student_name") or ticket.get("requester_name") or "the student"
    student_email = ticket.get("student_email") or ticket.get("requester_email") or ""

    header_lines: list[Any] = [
        f"Channel: {channel}",
        f"Student: {student_name}",
        f"Student email: {student_email}" if student_email else None,
        f"Subject: {ticket.get('subject')}" if ticket.get("subject") else None,
        f"Tier/Tags: {', '.join(ticket.get('tags') or [])}" if ticket.get("tags") else None,
    ]
    header = "\n".join(p for p in header_lines if p)
    body = _format_thread_for_prompt(thread)
    user_text = f"{header}\n\n--- THREAD ---\n{body}\n\n--- DRAFT YOUR REPLY BELOW ---"

    chat = LlmChat(
        api_key=key,
        session_id=f"ticket-triage-{ticket.get('id', 'x')}",
        system_message=_system_prompt(channel),
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")
    resp = await chat.send_message(UserMessage(text=user_text))
    draft = (resp or "").strip()
    # Strip surrounding fences / triple-quote artefacts just in case.
    if draft.startswith("```"):
        draft = draft.strip("`").strip()
    # Channel-specific hard cap
    cap = WHATSAPP_CHAR_LIMIT if channel == "whatsapp" else EMAIL_CHAR_LIMIT
    if len(draft) > cap:
        draft = draft[:cap].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return {"draft": draft, "channel": channel, "thread_size": len(thread)}
