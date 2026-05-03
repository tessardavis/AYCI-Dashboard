"""Spotlight Coaching: live-session signup roster."""
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException

import spotlight
import spotlight_slack
import spotlight_tracking
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
    payload = await spotlight.get_upcoming_spotlight_sessions(db, limit=max(1, min(int(limit), 6)))
    # Overlay spotlight-tracking records and "× spotlighted" counts
    counts = await spotlight_tracking.student_spotlight_counts(db)
    for s in payload.get("sessions") or []:
        records = await spotlight_tracking.list_for_session(db, s["id"])
        by_key = {
            r.get("student_name", "").strip().lower(): r for r in records
        }
        s["records"] = records
        for st in s.get("students") or []:
            key = (st.get("name") or "").strip().lower()
            rec = by_key.get(key)
            st["record"] = rec  # full record or None
            st["record_status"] = rec.get("status") if rec else None
            st["spotlight_count"] = counts.get(key, 0)
    return payload


@router.get("/spotlight/records")
async def list_records(
    session_id: int,
    user: dict = Depends(require_board("spotlight")),
):
    return {"records": await spotlight_tracking.list_for_session(db, session_id)}


@router.get("/spotlight/history")
async def history(
    limit: int = 40,
    user: dict = Depends(require_board("spotlight")),
):
    """Past spotlight sessions with their recorded outcomes. Grouped by
    session, newest session first."""
    return {"sessions": await spotlight_tracking.list_history(db, limit=limit)}


@router.post("/spotlight/records")
async def upsert_record(
    payload: dict = Body(...),
    user: dict = Depends(require_board("spotlight")),
):
    """Record or update a spotlight outcome for a (session, student).
    Body: `{session_id, student_name, status, notes?, student_email?, source?}`."""
    try:
        return await spotlight_tracking.upsert_record(
            db,
            session_id=int(payload["session_id"]),
            student_name=str(payload.get("student_name") or ""),
            status=str(payload.get("status") or ""),
            notes=str(payload.get("notes") or ""),
            student_email=payload.get("student_email"),
            source=str(payload.get("source") or "tally"),
            recorded_by=user.get("id") or user.get("email") or "unknown",
            recorded_by_name=user.get("name") or user.get("email") or "Unknown",
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))


@router.delete("/spotlight/records/{record_id}")
async def delete_record(
    record_id: str,
    user: dict = Depends(require_board("spotlight")),
):
    ok = await spotlight_tracking.delete_record(db, record_id)
    if not ok:
        raise HTTPException(404, "record not found")
    return {"ok": True}


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
