"""Support Tickets — REST endpoints + Tally webhook + sync."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

import tickets as tickets_mod
from db import db
from deps import get_current_user, require_board
from models import (
    Ticket, TicketCreate, TicketUpdate, TicketNote, TicketNoteCreate,
)

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# -------------------------------------------------------- List + filters
@router.get("")
async def list_tickets(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    assignee_id: Optional[str] = None,
    q: Optional[str] = None,
    user: dict = Depends(require_board("tickets")),
):
    query: dict = {}
    if status:
        query["status"] = status
    if priority:
        query["priority"] = priority
    if category:
        query["category"] = category
    if assignee_id is not None:
        if assignee_id == "":
            query["assignee_id"] = None
        else:
            query["assignee_id"] = assignee_id
    if q:
        rx = {"$regex": q, "$options": "i"}
        query["$or"] = [
            {"student_name": rx},
            {"student_email": rx},
            {"subject": rx},
            {"description": rx},
        ]

    rows = await db.tickets.find(query, {"_id": 0}).sort("created_at", -1).to_list(2000)
    now = datetime.now(timezone.utc)
    for r in rows:
        tickets_mod.enrich_ticket(r, now=now)
    return {"tickets": rows}


@router.get("/stats")
async def ticket_stats(user: dict = Depends(require_board("tickets"))):
    return await tickets_mod.compute_stats(db)


# -------------------------------------------------------- Create / read / update
@router.post("")
async def create_ticket(
    data: TicketCreate,
    background: BackgroundTasks,
    user: dict = Depends(require_board("tickets")),
):
    now = _now_iso()
    doc = Ticket(
        student_name=data.student_name.strip(),
        student_email=data.student_email.lower().strip(),
        subject=data.subject.strip(),
        description=data.description.strip(),
        priority=data.priority,
        category=data.category,
        assignee_id=data.assignee_id or None,
        source="manual",
        created_at=now,
        updated_at=now,
    ).model_dump()
    await db.tickets.insert_one(doc)
    if doc["priority"] == "urgent":
        background.add_task(tickets_mod.maybe_send_urgent_slack, db, doc)
    doc.pop("_id", None)
    return tickets_mod.enrich_ticket(doc)


@router.get("/{ticket_id}")
async def get_ticket(ticket_id: str, user: dict = Depends(require_board("tickets"))):
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Ticket not found")
    return tickets_mod.enrich_ticket(t)


@router.patch("/{ticket_id}")
async def update_ticket(
    ticket_id: str,
    data: TicketUpdate,
    background: BackgroundTasks,
    user: dict = Depends(require_board("tickets")),
):
    t = await db.tickets.find_one({"id": ticket_id})
    if not t:
        raise HTTPException(404, "Ticket not found")

    update: dict = {}
    if data.student_name is not None:
        update["student_name"] = data.student_name.strip()
    if data.student_email is not None:
        update["student_email"] = data.student_email.lower().strip()
    if data.subject is not None:
        update["subject"] = data.subject.strip()
    if data.description is not None:
        update["description"] = data.description.strip()
    if data.status is not None:
        update["status"] = data.status
        if data.status == "resolved" and not t.get("resolved_at"):
            update["resolved_at"] = _now_iso()
        if data.status != "resolved":
            update["resolved_at"] = None
    if data.priority is not None:
        update["priority"] = data.priority
        # Re-arm Slack if priority is escalated to urgent
        if data.priority == "urgent" and t.get("priority") != "urgent":
            update["slack_urgent_sent"] = False
    if data.category is not None:
        update["category"] = data.category
    if data.assignee_id is not None:
        update["assignee_id"] = data.assignee_id or None

    if not update:
        raise HTTPException(400, "No changes")
    update["updated_at"] = _now_iso()

    await db.tickets.update_one({"id": ticket_id}, {"$set": update})
    fresh = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})

    # Send Slack if newly urgent (creation OR escalation)
    if fresh.get("priority") == "urgent" and not fresh.get("slack_urgent_sent"):
        background.add_task(tickets_mod.maybe_send_urgent_slack, db, fresh)

    return tickets_mod.enrich_ticket(fresh)


@router.delete("/{ticket_id}")
async def delete_ticket(ticket_id: str, user: dict = Depends(require_board("tickets"))):
    res = await db.tickets.delete_one({"id": ticket_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Ticket not found")
    return {"ok": True}


# -------------------------------------------------------- Notes
@router.post("/{ticket_id}/notes")
async def add_note(
    ticket_id: str,
    data: TicketNoteCreate,
    user: dict = Depends(require_board("tickets")),
):
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Ticket not found")
    body = (data.body or "").strip()
    if not body:
        raise HTTPException(400, "Note body required")
    note = TicketNote(
        author_id=user["id"],
        author_name=user.get("name") or user.get("email") or "Unknown",
        body=body,
        created_at=_now_iso(),
        internal=data.internal,
    ).model_dump()
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$push": {"notes": note}, "$set": {"updated_at": _now_iso()}},
    )
    fresh = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    return tickets_mod.enrich_ticket(fresh)


# -------------------------------------------------------- Tally sync + webhook
@router.post("/tally/sync")
async def tally_sync(user: dict = Depends(require_board("tickets"))):
    """Manually trigger a sync from the AYCI Support Desk Tally form."""
    return await tickets_mod.sync_tally(db)


@router.post("/tally/webhook")
async def tally_webhook(request: Request, background: BackgroundTasks):
    """Public webhook endpoint for Tally to POST new submissions to.
    Uses Tally's webhook payload shape: `{eventType, data: {fields: [...]}}`.
    No auth — Tally signs with its own secret if configured (out of scope for
    Phase 1; rely on the form ID match instead)."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    data = payload.get("data") or {}
    form_id = data.get("formId") or payload.get("formId")
    if form_id != tickets_mod.TALLY_SUPPORT_FORM_ID:
        # Silently ignore — webhook may be configured for a different form.
        return {"ignored": True, "form_id": form_id}

    # Tally webhook shape: data.fields = [{key/label/value/...}]
    # Map back to our (questionId, answer) shape that `_ticket_from_tally_submission`
    # expects.
    responses: list[dict] = []
    for f in (data.get("fields") or []):
        key = f.get("key")
        responses.append({"questionId": key, "answer": f.get("value")})
    sub = {
        "id": data.get("submissionId") or data.get("responseId") or payload.get("eventId"),
        "submittedAt": data.get("createdAt") or payload.get("createdAt"),
        "responses": responses,
    }
    if not sub["id"]:
        raise HTTPException(400, "Missing submission id")

    existing = await db.tickets.find_one(
        {"source": "tally", "source_ref": sub["id"]}, {"_id": 1}
    )
    if existing:
        return {"ignored": True, "reason": "already exists"}

    ticket = tickets_mod._ticket_from_tally_submission(sub)
    if not ticket:
        raise HTTPException(400, "Could not build ticket — missing email")
    await db.tickets.insert_one(ticket)
    return {"ok": True, "ticket_id": ticket["id"]}
