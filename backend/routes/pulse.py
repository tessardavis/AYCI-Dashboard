"""Pulse Score: amalgamated team-health score for the Weekly Scorecard."""
from typing import Optional

from fastapi import APIRouter, Depends

import pulse_score
from db import db
from deps import get_current_user

router = APIRouter(prefix="/api", tags=["pulse"])


@router.get("/pulse-score")
async def pulse(
    week_start: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """Composite 0-100 health score across scorecard, rocks, SLA and at-risk
    students. `week_start` defaults to the most recent completed Monday."""
    return await pulse_score.compute_pulse_score(db, week_start=week_start)
