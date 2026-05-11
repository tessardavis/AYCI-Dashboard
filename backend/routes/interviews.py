"""Upcoming interviews + private tier utilisation."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

import upcoming_interviews as upcoming
import launches as launches_mod

from db import db
from deps import require_board

router = APIRouter(prefix="/api", tags=["interviews"])


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
    )
    today = datetime.now(timezone.utc).date()
    academy_cutoff = (today + timedelta(days=academy_days)).isoformat()
    academy = [s for s in data["academy"] if s["interview_date"] <= academy_cutoff]
    # Enrich every student with the over-allowance snapshot (no extra fetch —
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
    return {
        "academy_window": {"days": academy_days, "end": academy_cutoff},
        "private_window": {"days": private_days, "end": data["window"]["end"]},
        "today": today.isoformat(),
        "academy": academy,
        "private": data["private"],
    }


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
    )
