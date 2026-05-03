"""Cohort Leaderboard: top Circle badge earners for the active cohort."""
from fastapi import APIRouter, Depends

import leaderboard
from db import db
from deps import require_board

router = APIRouter(prefix="/api", tags=["leaderboard"])


@router.get("/leaderboard/cohort")
async def cohort_leaderboard(
    cohort: str = "Apr '26",
    limit: int = 25,
    user: dict = Depends(require_board("leaderboard")),
):
    """Top-`limit` members of the given cohort, ranked by Circle badge count
    (total tags − cohort tags − private-tier tags). Uses the existing
    `circle_members_cache`, so sub-100 ms."""
    rows = await leaderboard.get_top_leaderboard(db, cohort_tag=cohort, limit=max(1, min(int(limit), 100)))
    return {"cohort": cohort, "entries": rows, "total": len(rows)}
