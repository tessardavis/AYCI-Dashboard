"""Upcoming interviews + private tier utilisation."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import upcoming_interviews as upcoming
import launches as launches_mod

from db import db
from deps import require_board

router = APIRouter(prefix="/api", tags=["interviews"])


class InterviewDatePayload(BaseModel):
    # ISO YYYY-MM-DD, or null / empty string to clear the date.
    interview_date: str | None = None


@router.get("/interviews/upcoming")
async def upcoming_interviews(
    academy_days: int = 7,
    private_days: int = 14,
    user: dict = Depends(require_board("interviews")),
):
    """Upcoming interviews grouped by Academy vs private tiers. Academy uses
    `academy_days` window (default 7); private/boost uses `private_days` (14)."""
    wider = max(academy_days, private_days)
    data = await launches_mod._stale_while_revalidate(
        db,
        f"upcoming_interviews:{wider}",
        ttl_min=30,
        compute_fn=lambda: upcoming.fetch_upcoming_interviews(db=db, days=wider),
        day_sensitive=True,
    )
    today = datetime.now(timezone.utc).date()
    academy_cutoff = (today + timedelta(days=academy_days)).isoformat()
    academy = [s for s in data["academy"] if s["interview_date"] <= academy_cutoff]
    # Enrich every student with the over-allowance snapshot (no extra fetch -
    # uses the cached map written by the over_allowance_check scheduled job).
    import over_allowance_alerts as oaa
    over_snapshot = await oaa.get_cached_over_allowance(db)
    over_by_email = {
        (s.get("email") or "").lower(): s
        for s in (over_snapshot.get("students") or [])
    }
    for bucket in (academy, data["private"]):
        for s in bucket:
            em = (s.get("email") or "").lower()
            o = over_by_email.get(em)
            if o:
                s["over_allowance"] = {
                    "calendly_calls_used": o["calendly_calls_used"],
                    "monday_total_allowance": o["monday_total_allowance"],
                    "over_by": o["over_by"],
                }

    # Enrich each student with their interview-eve check-in score (if we've
    # already DM'd them for THIS interview's date). The score appears as a
    # chip on each row so the team sees pre-interview confidence at a glance.
    interview_dates = sorted({
        s.get("interview_date")
        for bucket in (academy, data["private"]) for s in bucket
        if s.get("interview_date")
    })
    if interview_dates:
        eve_rows = await db.interview_eve_dms.find(
            {"interview_date": {"$in": interview_dates}},
            {"_id": 0, "student_email": 1, "interview_date": 1, "score": 1,
             "score_received_at": 1, "sent_at": 1, "is_private_tier": 1},
        ).to_list(None)
        eve_by_key = {
            (r["student_email"], r["interview_date"]): r for r in eve_rows
        }
        for bucket in (academy, data["private"]):
            for s in bucket:
                em = (s.get("email") or "").lower()
                key = (em, s.get("interview_date"))
                rec = eve_by_key.get(key)
                if rec:
                    s["eve_score"] = {
                        "score": rec.get("score"),
                        "score_received_at": rec.get("score_received_at"),
                        "sent_at": rec.get("sent_at"),
                    }
    return {
        "academy_window": {"days": academy_days, "end": academy_cutoff},
        "private_window": {"days": private_days, "end": data["window"]["end"]},
        "today": today.isoformat(),
        "academy": academy,
        "private": data["private"],
    }


@router.patch("/interviews/{student_id}/interview-date")
async def set_interview_date(
    student_id: str,
    payload: InterviewDatePayload,
    user: dict = Depends(require_board("interviews")),
):
    """Set (or clear) a student's interview date directly in the dashboard.

    Writes straight to the academy_members mirror and PINS `interview_date` in
    `dashboard_edited_fields`, so the 15-minute Monday sync can no longer
    overwrite it - the dashboard becomes the source of truth for this date.
    This is the supported path for dates set outside the Tally form (which the
    Tally reconcile can't see). Pass interview_date=null/"" to clear.
    """
    new_date = (payload.interview_date or "").strip()[:10] or None
    if new_date is not None:
        try:
            datetime.fromisoformat(new_date)
        except ValueError:
            raise HTTPException(400, "interview_date must be ISO YYYY-MM-DD")

    row = await db.academy_members.find_one(
        {"_id": student_id},
        {"_id": 1, "name": 1, "interview_date": 1, "dashboard_edited_fields": 1},
    )
    if not row:
        raise HTTPException(404, "Student not found in the dashboard")

    now = datetime.now(timezone.utc)
    # Pin interview_date so academy_members_mirror.full_sync won't clobber it
    # (interview_date is already in mirror.PROTECTED_FIELDS).
    pinned = sorted(set(row.get("dashboard_edited_fields") or []) | {"interview_date"})
    editor = (user.get("email") or user.get("name") or "unknown") if isinstance(user, dict) else "unknown"
    await db.academy_members.update_one(
        {"_id": student_id},
        {"$set": {
            "interview_date": new_date,
            "interview_date_source": "dashboard",
            "interview_date_prev": row.get("interview_date"),
            "interview_date_reconciled_at": now,
            "dashboard_edited_fields": pinned,
            "dashboard_edited_at": now,
            "dashboard_edited_by": f"dashboard-edit:{editor}",
        }},
    )

    # Bust every cached Upcoming Interviews window so the change shows at once
    # (key is "upcoming_interviews:<wider>"; SWR otherwise serves it for 30 min).
    await db["fn_cache"].delete_many({"_id": {"$regex": "^upcoming_interviews:"}})

    # Best-effort: keep the AYCI Interviews calendar in step, same as the
    # Tally reconcile does. Inert unless the calendar is configured.
    try:
        import google_calendar
        if google_calendar.is_configured() and new_date:
            full = await db.academy_members.find_one({"_id": student_id})
            if full:
                await google_calendar.ensure_interview_event(db, full)
    except Exception:
        pass

    return {"ok": True, "student_id": student_id, "interview_date": new_date,
            "previous": row.get("interview_date")}


@router.get("/interviews/private-tier-utilisation")
async def private_tier_utilisation(
    days: int = 14,
    refresh: bool = False,
    user: dict = Depends(require_board("interviews")),
):
    """For PP + VIP students with an upcoming interview in the next `days`,
    flag who's under-utilising allowance vs on track. Cached 30 min via SWR."""
    if days not in (7, 14, 30):
        raise HTTPException(400, "days must be 7, 14 or 30")
    import private_tier_utilisation as ptu
    cache_key = f"private_tier_utilisation:{days}"
    if refresh:
        await db["fn_cache"].delete_one({"_id": cache_key})
    return await launches_mod._stale_while_revalidate(
        db, cache_key, ttl_min=30,
        compute_fn=lambda: ptu.fetch_private_tier_utilisation(days=days),
        day_sensitive=True,
    )
