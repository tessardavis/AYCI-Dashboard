"""
Support Tickets — Customer Service ticket system.

Sources:
- Manual entry from the dashboard
- Tally form ingestion (form id `D4BW1N` "AYCI Support Desk")
- Inbox auto-pull (Phase 2 — Gmail/Outlook)

Behaviour:
- Per-priority SLA (urgent=4h, high=24h, medium=48h, low=120h). Tickets older
  than the SLA in Open/In-Progress/Waiting status flag as overdue.
- New ticket marked Urgent (or escalated to Urgent) → Slack ping via
  `SLACK_WEBHOOK_URL`. Idempotency tracked via `slack_urgent_sent`.
- Notes thread per ticket (team-internal by default).

Mongo collections:
- `tickets`           — the ticket records
- `ticket_sync_state` — last Tally sync watermark (`{_id: "tally", last_submitted_at}`)
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

UK_TZ = ZoneInfo("Europe/London")

# Tally form that backs this system. Three fields:
#   62aD7J = Full name
#   726XWR = Email (Circle)
#   bxbZ7Z = What do you need help with?
TALLY_SUPPORT_FORM_ID = "D4BW1N"
TALLY_FIELD_NAME = "62aD7J"
TALLY_FIELD_EMAIL = "726XWR"
TALLY_FIELD_DESCRIPTION = "bxbZ7Z"

# SLA: open/in_progress/waiting tickets older than this become "overdue".
SLA_HOURS = {
    "urgent": 4,
    "high": 24,
    "medium": 48,
    "low": 120,
}

OPEN_STATUSES = {"open", "in_progress", "waiting"}


# -------------------------------------------------------- Helpers
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slack_webhook_url() -> Optional[str]:
    url = (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()
    return url or None


def is_overdue(ticket: dict, *, now: Optional[datetime] = None) -> bool:
    """Open ticket whose age exceeds its priority SLA."""
    if ticket.get("status") not in OPEN_STATUSES:
        return False
    created = ticket.get("created_at")
    if not created:
        return False
    try:
        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    if created_dt.tzinfo is None:
        created_dt = created_dt.replace(tzinfo=timezone.utc)
    sla_hrs = SLA_HOURS.get(ticket.get("priority", "medium"), 48)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=sla_hrs)
    return created_dt < cutoff


def enrich_ticket(ticket: dict, *, now: Optional[datetime] = None) -> dict:
    """Add computed fields (`overdue`) to a ticket dict in place. Drops `_id`."""
    ticket.pop("_id", None)
    ticket["overdue"] = is_overdue(ticket, now=now)
    return ticket


# -------------------------------------------------------- Slack
async def _post_slack_urgent(ticket: dict) -> bool:
    """Post an Urgent-ticket alert to Slack. Returns True on success."""
    url = _slack_webhook_url()
    if not url:
        logger.info("[tickets] Skipping Slack urgent — no SLACK_WEBHOOK_URL set")
        return False

    student = ticket.get("student_name") or ticket.get("student_email") or "Unknown"
    subject = ticket.get("subject") or "(no subject)"
    desc = (ticket.get("description") or "").strip()
    if len(desc) > 500:
        desc = desc[:500] + "…"
    category = (ticket.get("category") or "other").title()
    source = (ticket.get("source") or "manual").title()
    created = ticket.get("created_at") or _now_iso()
    try:
        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        uk = created_dt.astimezone(UK_TZ).strftime("%a %d %b · %H:%M UK")
    except Exception:
        uk = created

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🚨 Urgent support ticket — {student}", "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Subject*\n{subject}"},
                {"type": "mrkdwn", "text": f"*Category*\n{category}"},
                {"type": "mrkdwn", "text": f"*Source*\n{source}"},
                {"type": "mrkdwn", "text": f"*Logged*\n{uk}"},
            ],
        },
    ]
    if desc:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"```{desc}```"}})

    payload = {
        "text": f"🚨 Urgent support ticket — {student}: {subject}",
        "blocks": blocks,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(url, json=payload)
            if r.status_code >= 300:
                logger.warning(f"[tickets] Slack urgent post returned {r.status_code}: {r.text}")
                return False
        return True
    except Exception as e:
        logger.warning(f"[tickets] Slack urgent post failed: {e}")
        return False


async def maybe_send_urgent_slack(db, ticket: dict) -> None:
    """Send Slack ping if the ticket is Urgent and we haven't sent for it yet.
    Marks `slack_urgent_sent=True` on success (idempotent across re-saves)."""
    if ticket.get("priority") != "urgent" or ticket.get("slack_urgent_sent"):
        return
    sent = await _post_slack_urgent(ticket)
    if sent:
        await db.tickets.update_one(
            {"id": ticket["id"]}, {"$set": {"slack_urgent_sent": True}}
        )
        ticket["slack_urgent_sent"] = True


# -------------------------------------------------------- Tally ingestion
async def _tally_fetch_submissions(form_id: str, *, max_pages: int = 5) -> list[dict]:
    """Fetch up to `max_pages * 100` submissions ordered newest first."""
    token = os.environ.get("TALLY_API_KEY") or ""
    if not token:
        return []
    headers = {"Authorization": f"Bearer {token}"}
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=30.0) as c:
        for page in range(1, max_pages + 1):
            r = await c.get(
                f"https://api.tally.so/forms/{form_id}/submissions",
                headers=headers,
                params={"page": page, "limit": 100},
            )
            if r.status_code != 200:
                logger.warning(f"[tickets] Tally fetch page {page} returned {r.status_code}")
                break
            body = r.json() or {}
            subs = body.get("submissions") or []
            if not subs:
                break
            out.extend(subs)
            if not body.get("hasMore"):
                break
    return out


def _extract_tally_field(responses: list[dict], question_id: str) -> str:
    for r in responses or []:
        if r.get("questionId") == question_id:
            v = r.get("answer") or r.get("value")
            if isinstance(v, list):
                return ", ".join(str(x) for x in v)
            return str(v) if v is not None else ""
    return ""


def _ticket_from_tally_submission(sub: dict) -> Optional[dict]:
    """Build a Ticket dict from a Tally submission row. Returns None if the
    submission can't be mapped (missing email)."""
    responses = sub.get("responses") or []
    name = _extract_tally_field(responses, TALLY_FIELD_NAME).strip()
    email = _extract_tally_field(responses, TALLY_FIELD_EMAIL).strip().lower()
    desc = _extract_tally_field(responses, TALLY_FIELD_DESCRIPTION).strip()
    if not email:
        return None
    submitted = sub.get("submittedAt") or sub.get("createdAt") or _now_iso()
    # Subject = first ~80 chars of description (so the board reads cleanly)
    subject = (desc.splitlines()[0] if desc else "").strip()
    if len(subject) > 80:
        subject = subject[:77].rstrip() + "…"
    if not subject:
        subject = "Support request"
    return {
        "id": str(uuid.uuid4()),
        "student_name": name or email.split("@")[0],
        "student_email": email,
        "subject": subject,
        "description": desc,
        "status": "open",
        "priority": "medium",
        "category": "other",
        "assignee_id": None,
        "source": "tally",
        "source_ref": sub.get("id"),
        "created_at": submitted,
        "updated_at": submitted,
        "resolved_at": None,
        "notes": [],
        "slack_urgent_sent": False,
    }


async def sync_tally(db) -> dict:
    """Pull new submissions from the AYCI Support Desk Tally form and create
    tickets for any not yet ingested. Idempotent — uses `source_ref` (Tally
    submission id) as the dedup key. Also consults `ticket_source_dedup` so
    refs from previously-deleted tickets don't re-import."""
    submissions = await _tally_fetch_submissions(TALLY_SUPPORT_FORM_ID)
    if not submissions:
        return {"inserted": 0, "scanned": 0}

    existing_refs = set()
    cursor = db.tickets.find(
        {"source": "tally"}, {"_id": 0, "source_ref": 1}
    )
    async for d in cursor:
        ref = d.get("source_ref")
        if ref:
            existing_refs.add(ref)
    # Also pick up tombstones from previously-deleted tickets
    cursor2 = db.ticket_source_dedup.find(
        {"source": "tally"}, {"_id": 0, "source_ref": 1}
    )
    async for d in cursor2:
        ref = d.get("source_ref")
        if ref:
            existing_refs.add(ref)

    inserted = 0
    for sub in submissions:
        if sub.get("id") in existing_refs:
            continue
        ticket = _ticket_from_tally_submission(sub)
        if not ticket:
            continue
        await db.tickets.insert_one(ticket)
        inserted += 1

    return {"inserted": inserted, "scanned": len(submissions)}


# -------------------------------------------------------- Stats
async def compute_stats(db) -> dict:
    """Stats for the Weekly Scorecard widget."""
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    week_start_iso = week_start.isoformat()

    open_count = 0
    overdue_count = 0
    urgent_open_count = 0
    resolved_this_week = 0

    cursor = db.tickets.find(
        {},
        {"_id": 0, "status": 1, "priority": 1, "created_at": 1, "resolved_at": 1},
    )
    async for t in cursor:
        status = t.get("status")
        if status in OPEN_STATUSES:
            open_count += 1
            if is_overdue(t, now=now):
                overdue_count += 1
            if t.get("priority") == "urgent":
                urgent_open_count += 1
        if status == "resolved":
            ra = t.get("resolved_at")
            if ra and ra >= week_start_iso:
                resolved_this_week += 1

    return {
        "open": open_count,
        "overdue": overdue_count,
        "urgent_open": urgent_open_count,
        "resolved_this_week": resolved_this_week,
    }
