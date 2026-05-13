"""Interview-Eve DM routes — admin view of sent check-ins + manual trigger."""
from fastapi import APIRouter, Depends

import interview_eve_dm
from db import db
from deps import require_admin, require_board

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


@router.get("/summary")
async def summary(user: dict = Depends(require_board("coach_activity"))):
    """Aggregated view of the last 7 days of interview-eve DMs — for the
    Coach Activity widget. Returns counts (sent / replied / low / pending),
    averages, and the rows for today + tomorrow's interviews, split by
    tier so private-tier students can be tracked separately."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=7)).isoformat()
    rows = await db.interview_eve_dms.find(
        {"sent_at": {"$gte": cutoff}}, {"_id": 0},
    ).sort("interview_date", -1).to_list(None)
    today = now.date().isoformat()
    tomorrow = (now.date() + timedelta(days=1)).isoformat()

    def _stats(subset: list[dict]) -> dict:
        scored = [r for r in subset if r.get("score") is not None]
        avg = round(sum(r["score"] for r in scored) / len(scored), 1) if scored else None
        return {
            "sent": len(subset),
            "replied": len(scored),
            "pending": len(subset) - len(scored),
            "low_score": sum(1 for r in subset if (r.get("score") or 99) <= 5),
            "avg_score": avg,
        }

    private_rows = [r for r in rows if r.get("is_private_tier")]
    other_rows = [r for r in rows if not r.get("is_private_tier")]

    return {
        "window_days": 7,
        "counts": _stats(rows),
        "private_tier": _stats(private_rows),
        "academy_tier": _stats(other_rows),
        "focus": [r for r in rows if r.get("interview_date") in (today, tomorrow)],
        "private_tier_rows": [r for r in private_rows if r.get("score") is not None][:50],
        "today": today,
        "tomorrow": tomorrow,
    }


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
