"""Private-Tier Video Submissions routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from deps import require_board
from db import db
import private_videos as pv

router = APIRouter(prefix="/api/private-videos", tags=["private-videos"])


@router.get("")
async def list_submissions(
    force: bool = False,
    user: dict = Depends(require_board("private_videos")),
):
    return await pv.list_submissions(db, force=force)


@router.get("/users")
async def assignable_users(
    user: dict = Depends(require_board("private_videos")),
):
    return {"users": await pv.get_team_users()}


class PrivateVideoPatch(BaseModel):
    status_label: Optional[str] = None
    assignee_id: Optional[str] = None
    replied: Optional[str] = None
    reply_link: Optional[str] = None


@router.patch("/{item_id}")
async def update_submission(
    item_id: str,
    patch: PrivateVideoPatch,
    user: dict = Depends(require_board("private_videos")),
):
    # Only forward fields that are explicitly set (not the default Nones)
    payload = patch.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(400, "No editable fields supplied")
    return await pv.update_submission(db, item_id, payload)
