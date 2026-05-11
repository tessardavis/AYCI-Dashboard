"""Coach activity dashboard."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

import coach_activity as coach_act
import coach_activity_dismissals as dismissals
import launches as launches_mod
import over_allowance_alerts as over_alerts

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



# -- Over-allowance bookings ------------------------------------------------
@router.get("/coach-activity/over-allowance")
async def coach_activity_over_allowance(
    refresh: bool = False,
    user: dict = Depends(require_board("coach_activity")),
):
    """List of currently over-booked students (Calendly all-time private
    calls > Monday total allowance). Cached snapshot is refreshed by the
    5-min scheduled job; set `refresh=true` to recompute immediately."""
    if refresh:
        snapshot = await over_alerts.find_over_allowance_students(db)
        await db.fn_cache.update_one(
            {"_id": over_alerts.OVER_ALLOWANCE_CACHE_KEY},
            {"$set": {"_id": over_alerts.OVER_ALLOWANCE_CACHE_KEY,
                      "value": snapshot,
                      "computed_at": snapshot["computed_at"]}},
            upsert=True,
        )
        return snapshot
    return await over_alerts.get_cached_over_allowance(db)


@router.post("/coach-activity/over-allowance/notify")
async def coach_activity_over_allowance_notify(
    user: dict = Depends(require_board("coach_activity")),
):
    """Force the over-allowance check + Slack DM to Oksana right now.
    Useful for testing or after a manual Monday-allowance fix."""
    return await over_alerts.notify_over_allowance_breaches(db)
