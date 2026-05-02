"""Spotlight Coaching: live-session signup roster."""
from fastapi import APIRouter, Depends

import spotlight
from db import db
from deps import require_board

router = APIRouter(prefix="/api", tags=["spotlight"])


@router.get("/spotlight/sessions")
async def list_spotlight_sessions(
    limit: int = 3,
    user: dict = Depends(require_board("spotlight")),
):
    """Next `limit` upcoming Circle Curriculum / General Coaching sessions with
    each session's spotlight Tally submissions, cross-referenced against the
    interview Tally form for "interview soon" prioritisation.

    Cached 15 min upstream (Tally + Circle), so this endpoint is sub-100 ms
    after first warm.
    """
    return await spotlight.get_upcoming_spotlight_sessions(db, limit=max(1, min(int(limit), 6)))
