"""Interview-Eve DM routes — admin view of sent check-ins + manual trigger."""
from fastapi import APIRouter, Depends

import interview_eve_dm
from db import db
from deps import require_admin

router = APIRouter(prefix="/api/interview-eve", tags=["interview-eve"])


@router.get("/records")
async def list_records(admin: dict = Depends(require_admin), limit: int = 100):
    """Recent interview-eve DM records (newest first), including any score
    the student replied with and whether a low-score alert was fired."""
    rows = await db.interview_eve_dms.find(
        {}, {"_id": 0},
    ).sort("sent_at", -1).limit(min(max(1, limit), 500)).to_list(500)
    return {"records": rows, "total": len(rows)}


@router.post("/run-now")
async def run_now(admin: dict = Depends(require_admin)):
    """Force the interview-eve job to run immediately (for testing)."""
    return await interview_eve_dm.send_interview_eve_dms(db)


@router.get("/preview")
async def preview(admin: dict = Depends(require_admin)):
    """Dry-run: who WOULD we DM if the job ran right now? No DMs sent."""
    import upcoming_interviews
    from datetime import datetime, timezone, timedelta
    target_date = (
        (datetime.now(timezone.utc) + timedelta(hours=1)).date() + timedelta(days=1)
    ).isoformat()
    payload = await upcoming_interviews.fetch_upcoming_interviews(db=db, days=3)
    candidates = []
    for group in ("academy", "private"):
        for s in payload.get(group) or []:
            if s.get("interview_date") == target_date:
                m = await interview_eve_dm._find_circle_member_by_email(
                    db, s.get("email") or "",
                )
                already = await db.interview_eve_dms.find_one(
                    {"student_email": (s.get("email") or "").lower(),
                     "interview_date": target_date},
                    {"_id": 0, "id": 1, "score": 1},
                )
                candidates.append({
                    "name": s.get("name"),
                    "email": s.get("email"),
                    "tier": s.get("tier"),
                    "is_private_tier": interview_eve_dm._is_private_tier(s),
                    "circle_member_id": (m or {}).get("id"),
                    "already_sent": bool(already),
                    "previous_score": (already or {}).get("score"),
                })
    return {"target_date": target_date, "candidates": candidates,
            "total": len(candidates)}
