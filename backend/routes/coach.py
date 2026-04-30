"""Coach activity dashboard."""
from fastapi import APIRouter, Depends

import coach_activity as coach_act
import launches as launches_mod

from db import db
from deps import require_board

router = APIRouter(prefix="/api", tags=["coach"])


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
