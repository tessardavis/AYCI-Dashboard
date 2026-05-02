"""Spotlight Coaching: live-session signup roster."""
from fastapi import APIRouter, Depends, HTTPException

import spotlight
import spotlight_slack
from db import db
from deps import require_admin, require_board

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


@router.post("/spotlight/slack/test")
async def slack_test(session_id: int, admin: dict = Depends(require_admin)):
    """Admin-only: dry-run the 30-min Slack reminder for a specific session id.
    Useful for sanity-checking the digest formatting without waiting for the
    cron to fire."""
    result = await spotlight_slack.send_session_reminder_now(db, session_id)
    if not result.get("sent") and result.get("error", "").startswith("session"):
        raise HTTPException(404, result["error"])
    return result


@router.post("/spotlight/slack/check-now")
async def slack_check_now(admin: dict = Depends(require_admin)):
    """Admin-only: run the same logic as the every-5-min cron right now.
    Sends Slack messages for any session in the 25-35 min window that hasn't
    been notified yet."""
    return await spotlight_slack.check_and_send_reminders(db)
