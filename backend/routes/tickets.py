"""Support Tickets — REST endpoints + Tally webhook + sync."""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import tickets as tickets_mod
from db import db
from deps import get_current_user, require_board
from models import (
    Ticket, TicketCreate, TicketUpdate, TicketNote, TicketNoteCreate,
)


class BulkCloseRequest(BaseModel):
    ids: List[str] = Field(..., min_length=1, max_length=500)

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
    # Build a map of (this user's last-viewed timestamp per ticket) so we can
    # mark each card as having "new" activity since they last opened it.
    views = await db.ticket_views.find(
        {"user_id": user["id"]},
        {"_id": 0, "ticket_id": 1, "viewed_at": 1},
    ).to_list(5000)
    viewed_map = {v["ticket_id"]: v["viewed_at"] for v in views}
    now = datetime.now(timezone.utc)
    for r in rows:
        tickets_mod.enrich_ticket(r, now=now)
        last_view = viewed_map.get(r["id"])
        # Unread if the ticket has been updated since the user last opened it.
        # Brand-new tickets (never viewed) count as unread too. We compare
        # against `updated_at` which advances on every reply / note / status
        # change.
        upd = r.get("updated_at") or r.get("created_at") or ""
        r["unread"] = (not last_view) or (last_view < upd)
        r["last_viewed_at"] = last_view
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
    # Mark this ticket as viewed by the current user so the "new" badge clears
    # on the Kanban board next refresh.
    now_iso = _now_iso()
    await db.ticket_views.update_one(
        {"user_id": user["id"], "ticket_id": ticket_id},
        {"$set": {"user_id": user["id"], "ticket_id": ticket_id, "viewed_at": now_iso}},
        upsert=True,
    )
    # Clear the Circle-activity unread badge: opening the ticket counts as
    # the team having seen the forwarded student replies. Global (not
    # per-user) — once any coach opens it, the badge clears for everyone,
    # which matches how the team works (the first responder owns it).
    if (t.get("unread_circle_count") or 0) > 0:
        await db.tickets.update_one(
            {"id": ticket_id},
            {"$set": {
                "unread_circle_count": 0,
                "circle_activity_acknowledged_at": now_iso,
                "circle_activity_acknowledged_by": user.get("email") or user.get("name"),
            }},
        )
        t["unread_circle_count"] = 0
        t["circle_activity_acknowledged_at"] = now_iso
    # Lazy-match to Monday so the team sees student context without an extra round-trip
    try:
        import student_match as sm
        await sm.ensure_ticket_student_match(db, t)
    except Exception:
        pass
    return tickets_mod.enrich_ticket(t)


@router.post("/{ticket_id}/match-student")
async def match_student_now(ticket_id: str, user: dict = Depends(require_board("tickets"))):
    """Force-refresh the student_match cache on this ticket."""
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Ticket not found")
    import student_match as sm
    match = await sm.ensure_ticket_student_match(db, t, force=True)
    return match


@router.post("/bulk-close")
async def bulk_close_tickets(
    payload: BulkCloseRequest,
    user: dict = Depends(require_board("tickets")),
):
    """Close many tickets in one shot. Used by the bulk action toolbar on
    the Support Tickets board so the team can clear backlog quickly."""
    now = _now_iso()
    res = await db.tickets.update_many(
        {"id": {"$in": payload.ids}, "status": {"$ne": "closed"}},
        {"$set": {
            "status": "closed",
            "resolved_at": now,
            "updated_at": now,
        }},
    )
    return {"ok": True, "closed": res.modified_count, "requested": len(payload.ids)}


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

    # Send Slack DM if assignee changed (and is now someone). Skip if the user
    # is assigning to themselves — they already know.
    if (
        data.assignee_id is not None
        and update.get("assignee_id")
        and update["assignee_id"] != t.get("assignee_id")
    ):
        background.add_task(
            tickets_mod.maybe_send_assignment_dm,
            db, fresh, update["assignee_id"], user.get("id"),
        )

    # Send Slack if newly urgent (creation OR escalation)
    if fresh.get("priority") == "urgent" and not fresh.get("slack_urgent_sent"):
        background.add_task(tickets_mod.maybe_send_urgent_slack, db, fresh)

    return tickets_mod.enrich_ticket(fresh)


@router.delete("/{ticket_id}/notes/{note_id}")
async def delete_note(
    ticket_id: str,
    note_id: str,
    user: dict = Depends(require_board("tickets")),
):
    """Delete a single note from a ticket — handy for cleaning up duplicate
    inbound replies (e.g. when reconciliation races with webhook delivery)."""
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0, "notes": 1})
    if not t:
        raise HTTPException(404, "Ticket not found")
    note = next((n for n in (t.get("notes") or []) if n.get("id") == note_id), None)
    if not note:
        raise HTTPException(404, "Note not found")
    # GC any GridFS attachments owned by this note
    try:
        import attachments as att_store
        for att in note.get("attachments") or []:
            await att_store.delete_attachment(db, att.get("id"))
    except Exception:
        pass
    pull_ops = {"$pull": {"notes": {"id": note_id}}}
    if note.get("wati_message_id"):
        pull_ops["$pull"]["wati_message_ids"] = note["wati_message_id"]
    pull_ops["$set"] = {"updated_at": _now_iso()}
    await db.tickets.update_one({"id": ticket_id}, pull_ops)
    return {"ok": True, "deleted_id": note_id}


@router.delete("/{ticket_id}")
async def delete_ticket(ticket_id: str, user: dict = Depends(require_board("tickets"))):
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Ticket not found")
    # GC any GridFS attachments
    try:
        import attachments as att_store
        await att_store.delete_for_ticket(db, t)
    except Exception:
        pass
    await db.tickets.delete_one({"id": ticket_id})
    return {"ok": True}


@router.get("/{ticket_id}/attachments/{attachment_id}")
async def download_attachment(
    ticket_id: str, attachment_id: str, user: dict = Depends(require_board("tickets")),
):
    """Stream an attachment back to the browser. Used both for inline image
    preview and for the download button."""
    t = await db.tickets.find_one(
        {"id": ticket_id},
        {"_id": 0, "attachments": 1, "notes": 1},
    )
    if not t:
        raise HTTPException(404, "Ticket not found")

    # Look in top-level attachments AND in note-level attachments
    target = None
    for a in (t.get("attachments") or []):
        if a.get("id") == attachment_id:
            target = a
            break
    if not target:
        for n in (t.get("notes") or []):
            for a in (n.get("attachments") or []):
                if a.get("id") == attachment_id:
                    target = a
                    break
            if target:
                break
    if not target:
        raise HTTPException(404, "Attachment not found")

    import attachments as att_store
    try:
        stream = await att_store.open_download_stream(db, target["gridfs_id"])
    except Exception:
        raise HTTPException(404, "Attachment file missing")

    async def _iter():
        try:
            while True:
                chunk = await stream.readchunk()
                if not chunk:
                    break
                yield chunk
        finally:
            stream.close()

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        _iter(),
        media_type=target.get("mime_type") or "application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{target.get("filename") or "attachment"}"',
            "Cache-Control": "private, max-age=300",
        },
    )


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
    pending_files = ticket.pop("_pending_tally_files", [])
    if pending_files:
        ticket["attachments"] = await tickets_mod._fetch_tally_attachments(db, pending_files)
    await db.tickets.insert_one(ticket)
    return {"ok": True, "ticket_id": ticket["id"]}
