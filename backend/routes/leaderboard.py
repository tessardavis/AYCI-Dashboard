"""Cohort Leaderboard: top Circle badge earners for the active cohort."""
from fastapi import APIRouter, Depends, HTTPException

import leaderboard
import leaderboard_snapshots
from db import db
from deps import require_admin, require_board

router = APIRouter(prefix="/api", tags=["leaderboard"])


@router.get("/leaderboard/cohort")
async def cohort_leaderboard(
    cohort: str = "Apr '26",
    limit: int = 25,
    user: dict = Depends(require_board("leaderboard")),
):
    """Top-`limit` members of the given cohort, ranked by Circle badge count
    (total tags − cohort tags − private-tier tags). Includes each member's
    specific badges + their week-over-week delta (if a prior snapshot exists)
    and the biggest-climbers list for that cohort."""
    rows = await leaderboard.get_top_leaderboard(
        db, cohort_tag=cohort, limit=max(1, min(int(limit), 100))
    )
    deltas = await leaderboard_snapshots.get_week_over_week(db, cohort, days=7)
    for r in rows:
        d = deltas.get(r.get("email") or "")
        r["delta"] = d["delta"] if d else None
        r["new_badges"] = d["new_badges"] if d else []
        r["delta_snapshot_date"] = d.get("snapshot_date") if d else None
    climbers = await leaderboard_snapshots.get_biggest_climbers(
        db, cohort, days=7, limit=5
    )
    return {
        "cohort": cohort,
        "entries": rows,
        "total": len(rows),
        "biggest_climbers": climbers,
    }


@router.post("/leaderboard/snapshot")
async def snapshot_now(cohort: str = "", admin: dict = Depends(require_admin)):
    """Admin-only: force a leaderboard snapshot right now. Useful to seed the
    first week's comparison data on day 1 instead of waiting for the cron.

    Pass `?cohort=...` to snapshot a single cohort, omit to snapshot all."""
    if cohort:
        return {"written": await leaderboard_snapshots.snapshot_cohort(db, cohort)}
    return {"written": await leaderboard_snapshots.snapshot_all_active_cohorts(db)}
