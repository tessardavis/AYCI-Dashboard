"""Private-Tier Video Submissions — DB-backed routes (replaces Monday board)."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from db import db
from deps import require_admin, require_board
import private_videos_store as pv_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/private-videos", tags=["private-videos"])


# ------------------------------------------------------------- READ
@router.get("")
async def list_submissions(
    force: bool = False,  # legacy param, kept so existing frontend URLs work
    user: dict = Depends(require_board("private_videos")),
):
    return await pv_store.list_submissions(db, force=force)


@router.get("/users")
async def assignable_users(
    user: dict = Depends(require_board("private_videos")),
):
    """Returns the assignee dropdown — now uses our internal team_members
    rather than Monday users. Same shape as before so the frontend works."""
    return {"users": await pv_store.get_team_users(db)}


# ------------------------------------------------------------- WRITE
class PrivateVideoPatch(BaseModel):
    status_label: Optional[str] = None
    assignee_id: Optional[str] = None  # now a team_member id
    replied: Optional[str] = None
    reply_link: Optional[str] = None
    private_chat_url: Optional[str] = None
    interview_date: Optional[str] = None


@router.patch("/{item_id}")
async def update_submission(
    item_id: str,
    patch: PrivateVideoPatch,
    user: dict = Depends(require_board("private_videos")),
):
    payload = patch.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(400, "No editable fields supplied")
    res = await pv_store.update_submission(db, item_id, payload)
    if not res.get("ok"):
        raise HTTPException(404, res.get("reason") or "Update failed")
    return res["item"]


# ------------------------------------------------------------- TALLY WEBHOOK
@router.post("/tally-webhook")
async def tally_webhook(request: Request):
    """Public webhook Tally posts to whenever a private-tier video is submitted.
    Configure in Tally: form 0Qr5py → Integrations → Webhook URL =
    https://<host>/api/private-videos/tally-webhook"""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")
    try:
        return await pv_store.ingest_tally_submission(db, payload)
    except Exception as e:
        # Never 500 — Tally would aggressively retry. Log and ack.
        logger.exception(f"[private-videos] tally webhook error: {e}")
        return {"ok": False, "error": str(e)}


# ------------------------------------------------------------- ADMIN
@router.post("/migrate-from-monday")
async def migrate_from_monday(admin: dict = Depends(require_admin)):
    """One-off migration: pull all 462 rows from Monday board 5083952249 and
    upsert into MongoDB. Idempotent — safe to re-run."""
    return await pv_store.migrate_from_monday(db)


@router.get("/stats")
async def stats(user: dict = Depends(require_board("private_videos"))):
    """Quick health check for the admin: how many rows in DB, and how many of
    those came from Monday vs Tally."""
    total = await db.private_video_submissions.count_documents({})
    from_monday = await db.private_video_submissions.count_documents(
        {"monday_item_id": {"$ne": None}}
    )
    from_tally = await db.private_video_submissions.count_documents(
        {"tally_submission_id": {"$ne": None}}
    )
    return {"total": total, "from_monday": from_monday, "from_tally": from_tally}
