"""Coach activity dashboard."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

import coach_activity as coach_act
import coach_activity_dismissals as dismissals
import launches as launches_mod

from db import db
from deps import require_board

router = APIRouter(prefix="/api", tags=["coach"])


class DismissRequest(BaseModel):
    alert_type: Literal["unanswered", "rate_limited"]
    key: str = Field(..., min_length=1, max_length=300)


@router.get("/coach-activity/summary")
async def coach_activity_summary(
    refresh: bool = False,
    user: dict = Depends(require_board("coach_activity")),
):
    """Aggregated coaching engagement across Circle spaces + private video
    responses. Cached 30 min via SWR."""
    if refresh:
        await db["fn_cache"].delete_one({"_id": "coach_activity:summary"})
    return await launches_mod._stale_while_revalidate(
        db,
        "coach_activity:summary",
        ttl_min=30,
        compute_fn=lambda: coach_act.fetch_coach_activity_summary(db),
    )


@router.post("/coach-activity/dismiss")
async def coach_activity_dismiss(
    payload: DismissRequest,
    user: dict = Depends(require_board("coach_activity")),
):
    """Mark an Awaiting-coach-reply or Posting>3/week alert as 'not needed'.
    Dismissals are SHARED across the team and persist forever. The same
    dedup key also suppresses future Slack pings for rate-limited alerts."""
    res = await dismissals.dismiss(
        db,
        alert_type=payload.alert_type,
        key=payload.key,
        by_user_id=user.get("id"),
        by_name=user.get("name"),
    )
    # Bust the SWR cache so the freshly-dismissed item disappears immediately
    await db["fn_cache"].delete_one({"_id": "coach_activity:summary"})
    return res


@router.post("/coach-activity/undismiss")
async def coach_activity_undismiss(
    payload: DismissRequest,
    user: dict = Depends(require_board("coach_activity")),
):
    """Restore a previously-dismissed alert (in case it was a mistake)."""
    if not user:
        raise HTTPException(401, "auth required")
    res = await dismissals.undismiss(
        db, alert_type=payload.alert_type, key=payload.key,
    )
    await db["fn_cache"].delete_one({"_id": "coach_activity:summary"})
    return res
