"""Launch CRUD + analytics (registrations, sales, pace, comparisons)."""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException

import launches as launches_mod
import onboarding_gap as ob_gap

from db import db
from deps import get_current_user, require_admin, require_board
from models import (
    Launch, LaunchCreate, LaunchUpdate,
    LaunchData, LaunchDataUpdate,
    DailyRegistration, DailyRegistrationInput,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["launches"])


# ---- helpers --------------------------------------------------------------
def _launch_window(launch: dict) -> tuple[str, str]:
    start = launch.get("start_date")
    end = launch.get("end_date") or launch.get("webinar_date")

    def _iso(s: str) -> str:
        if "T" in s:
            return s if s.endswith("Z") else s + "Z" if "+" not in s else s
        return f"{s}T00:00:00Z"
    return _iso(start), _iso(end if "T" in end else end + "T23:59:59")


# ---- Launch CRUD ----------------------------------------------------------
@router.get("/launches", response_model=List[Launch])
async def list_launches(user: dict = Depends(get_current_user)):
    return await db.launches.find({}, {"_id": 0}).to_list(1000)


@router.post("/launches", response_model=Launch)
async def create_launch(data: LaunchCreate, admin: dict = Depends(require_admin)):
    lc = Launch(**data.model_dump())
    await db.launches.insert_one(lc.model_dump())
    ld = LaunchData(launch_id=lc.id)
    await db.launch_data.insert_one(ld.model_dump())
    return lc


@router.delete("/launches/{launch_id}")
async def delete_launch(launch_id: str, admin: dict = Depends(require_admin)):
    await db.launches.delete_one({"id": launch_id})
    await db.launch_data.delete_many({"launch_id": launch_id})
    await db.daily_registrations.delete_many({"launch_id": launch_id})
    return {"ok": True}


@router.patch("/launches/{launch_id}", response_model=Launch)
async def update_launch(launch_id: str, data: LaunchUpdate, admin: dict = Depends(require_admin)):
    updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if updates:
        await db.launches.update_one({"id": launch_id}, {"$set": updates})
    launch = await db.launches.find_one({"id": launch_id}, {"_id": 0})
    if not launch:
        raise HTTPException(404, "Launch not found")
    return launch


@router.get("/launches/{launch_id}/data")
async def get_launch_data(launch_id: str, user: dict = Depends(get_current_user)):
    data = await db.launch_data.find_one({"launch_id": launch_id}, {"_id": 0})
    if not data:
        ld = LaunchData(launch_id=launch_id)
        await db.launch_data.insert_one(ld.model_dump())
        return ld.model_dump()
    return data


@router.patch("/launches/{launch_id}/data")
async def update_launch_data(launch_id: str, data: LaunchDataUpdate, user: dict = Depends(get_current_user)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    existing = await db.launch_data.find_one({"launch_id": launch_id})
    if not existing:
        ld = LaunchData(launch_id=launch_id, **updates)
        await db.launch_data.insert_one(ld.model_dump())
        return ld.model_dump()
    if updates:
        await db.launch_data.update_one({"launch_id": launch_id}, {"$set": updates})
    return await db.launch_data.find_one({"launch_id": launch_id}, {"_id": 0})


@router.get("/launches/{launch_id}/daily-registrations")
async def list_daily_regs(launch_id: str, user: dict = Depends(get_current_user)):
    return await db.daily_registrations.find(
        {"launch_id": launch_id}, {"_id": 0}
    ).sort("date", 1).to_list(10000)


@router.post("/daily-registrations")
async def upsert_daily_registration(
    data: DailyRegistrationInput, user: dict = Depends(get_current_user),
):
    existing = await db.daily_registrations.find_one(
        {"launch_id": data.launch_id, "date": data.date}
    )
    if existing:
        await db.daily_registrations.update_one(
            {"launch_id": data.launch_id, "date": data.date},
            {"$set": {"count": data.count}},
        )
        return {"id": existing["id"], **data.model_dump()}
    dr = DailyRegistration(**data.model_dump())
    await db.daily_registrations.insert_one(dr.model_dump())
    return dr.model_dump()


# ---- Launch analytics -----------------------------------------------------
@router.get("/launches/year-overview")
async def launches_year_overview(user: dict = Depends(get_current_user)):
    """All launches with date ranges + Stripe revenue. Cached 1 h."""
    today_iso = datetime.now(timezone.utc).date().isoformat()
    cache_key = f"year-overview:{today_iso}"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    cached = await db.pace_cache.find_one({"_id": cache_key}, {"_id": 0})
    if cached and cached.get("cached_at"):
        c_at = cached["cached_at"]
        if c_at.tzinfo is None:
            c_at = c_at.replace(tzinfo=timezone.utc)
        if c_at > cutoff:
            return {**cached["payload"], "cached": True}

    all_launches = await db.launches.find({}, {"_id": 0}).sort("start_date", 1).to_list(50)

    async def _enrich(L: dict) -> dict:
        if not L.get("start_date") or not L.get("end_date"):
            return {**L, "revenue_gbp": 0, "sales_count": 0, "is_active": False, "is_future": False}
        try:
            sales = await launches_mod.cached_fetch_sales(
                db,
                L["start_date"] + "T00:00:00Z",
                L["end_date"] + "T23:59:59Z",
            )
            revenue = sales.get("total_amount_gbp", 0)
            count = sales.get("total_count", 0)
        except Exception:
            revenue, count = 0, 0
        return {
            "id": L["id"], "name": L["name"], "code": L.get("code"),
            "start_date": L["start_date"], "end_date": L["end_date"],
            "webinar_date": L.get("webinar_date"),
            "target_good": L.get("target_good"),
            "target_better": L.get("target_better"),
            "target_best": L.get("target_best"),
            "revenue_gbp": revenue, "sales_count": count,
            "is_active": L["start_date"] <= today_iso <= L["end_date"],
            "is_future": L["start_date"] > today_iso,
            "is_past": L["end_date"] < today_iso,
        }

    enriched = await asyncio.gather(*[_enrich(L) for L in all_launches])
    payload = {"today": today_iso, "launches": enriched}
    await db.pace_cache.update_one(
        {"_id": cache_key},
        {"$set": {"payload": payload, "cached_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return {**payload, "cached": False}


@router.get("/launches/active/pace")
async def active_launch_pace(user: dict = Depends(get_current_user)):
    """Pace for the currently-active launch. Cached 1 h."""
    today_iso = datetime.now(timezone.utc).date().isoformat()
    active = await db.launches.find_one(
        {"start_date": {"$lte": today_iso}, "end_date": {"$gte": today_iso}}, {"_id": 0}
    )
    if not active:
        return {"active": False, "message": "No active launch"}

    cache_key = f"pace:{active['id']}:{today_iso}"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    cached = await db.pace_cache.find_one({"_id": cache_key}, {"_id": 0})
    if cached and cached.get("cached_at"):
        c_at = cached["cached_at"]
        if c_at.tzinfo is None:
            c_at = c_at.replace(tzinfo=timezone.utc)
        if c_at > cutoff:
            return {**cached["payload"], "cached": True}

    all_launches = await db.launches.find({}, {"_id": 0}).sort("start_date", -1).to_list(50)
    previous = [
        L for L in all_launches
        if L["id"] != active["id"] and L.get("start_date", "") < active["start_date"]
    ][:3]
    pace = await launches_mod.compute_pace(db, active, previous)
    pace["active"] = True
    pace["launch_id"] = active["id"]
    pace["launch_name"] = active["name"]
    pace["webinar_date"] = active.get("webinar_date")
    await db.pace_cache.update_one(
        {"_id": cache_key},
        {"$set": {"payload": pace, "cached_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return {**pace, "cached": False}


@router.get("/launches/{launch_id}/registrations")
async def launch_registrations(launch_id: str, user: dict = Depends(get_current_user)):
    """Webinar registrations from Kit, by source + by day, for this launch."""
    launch = await db.launches.find_one({"id": launch_id}, {"_id": 0})
    if not launch:
        raise HTTPException(404, "Launch not found")
    code = launch.get("code")
    if not code:
        raise HTTPException(
            400,
            "Launch has no `code` set. Add the Kit tag prefix code (e.g. APR-26) "
            "in Settings before loading registrations.",
        )
    start, end = _launch_window(launch)
    return await launches_mod.cached_fetch_registrations(db, code, start, end)


@router.get("/launches/{launch_id}/sales")
async def launch_sales(launch_id: str, user: dict = Depends(get_current_user)):
    """Successful Stripe charges within the launch window, daily + by product."""
    launch = await db.launches.find_one({"id": launch_id}, {"_id": 0})
    if not launch:
        raise HTTPException(404, "Launch not found")
    start, end = _launch_window(launch)
    return await launches_mod.cached_fetch_sales(db, start, end)


@router.get("/launches/{launch_id}/onboarding-gap")
async def launch_onboarding_gap(
    launch_id: str,
    refresh: bool = False,
    user: dict = Depends(require_board("launches")),
):
    """New-signup customers for this launch not yet in the cohort's Circle
    spaces (per Monday "On Circle" status). Cached 30 min."""
    launch = await db.launches.find_one({"id": launch_id}, {"_id": 0})
    if not launch:
        raise HTTPException(404, "Launch not found")

    cache_key = f"onboarding_gap:{launch_id}"
    if refresh:
        await db["fn_cache"].delete_one({"_id": cache_key})

    async def _compute():
        return await ob_gap.fetch_onboarding_gap(launch)

    return await launches_mod._stale_while_revalidate(
        db, cache_key, ttl_min=30, compute_fn=_compute,
    )


@router.get("/launches/{launch_id}/phase-breakdown")
async def launch_phase_breakdown(
    launch_id: str,
    refresh: bool = False,
    user: dict = Depends(get_current_user),
):
    """Per-phase signups + revenue + registrations (current + previous 2).
    Cached 24 h, pre-warmed daily at 05:25 London."""
    launch = await db.launches.find_one({"id": launch_id}, {"_id": 0})
    if not launch:
        raise HTTPException(404, "Launch not found")

    cache_key = f"phase-breakdown:{launch_id}"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    cached = await db.cache.find_one({"_id": cache_key}, {"_id": 0})
    fresh = False
    if cached and cached.get("cached_at"):
        cached_at = cached["cached_at"]
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        fresh = cached_at > cutoff

    async def _warm():
        try:
            payload = await launches_mod.compute_phase_breakdown(db.launches, launch)
            await db.cache.update_one(
                {"_id": cache_key},
                {"$set": {"payload": payload, "cached_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
        except Exception as e:
            logger.warning(f"[phase-breakdown] Warm failed for {launch_id}: {e}")

    if refresh or not fresh:
        asyncio.create_task(_warm())

    if cached:
        return {**cached["payload"], "cached": True, "stale": not fresh}

    return {
        "computing": True,
        "current": {
            "id": launch_id, "code": launch.get("code"),
            "name": launch.get("name"), "phases": [],
        },
        "previous": [],
        "message": "First-time scan running in the background — refresh in 2-3 minutes.",
    }


@router.get("/launches/{launch_id}/comparison")
async def launch_comparison(
    launch_id: str,
    n_previous: int = 2,
    user: dict = Depends(get_current_user),
):
    """Registration + sales series for this launch + N previous, normalised
    to day-from-start so charts can overlay them."""
    current = await db.launches.find_one({"id": launch_id}, {"_id": 0})
    if not current:
        raise HTTPException(404, "Launch not found")

    all_launches = await db.launches.find({}, {"_id": 0}).sort("start_date", -1).to_list(50)
    others = [
        L for L in all_launches
        if L["id"] != launch_id and L.get("start_date", "") < current["start_date"]
        and L.get("code")
    ][:n_previous]

    async def _series(L: dict) -> dict:
        try:
            start, end = _launch_window(L)
            regs, sales = await asyncio.gather(
                launches_mod.cached_fetch_registrations(db, L["code"], start, end),
                launches_mod.cached_fetch_sales(db, start, end),
                return_exceptions=True,
            )
            return {
                "id": L["id"], "name": L["name"], "code": L.get("code"),
                "start_date": L["start_date"],
                "registrations": regs if not isinstance(regs, Exception) else None,
                "sales": sales if not isinstance(sales, Exception) else None,
                "registrations_aligned": (
                    launches_mod.align_by_day_offset(regs.get("by_day", []), start)
                    if not isinstance(regs, Exception) else []
                ),
                "sales_aligned": (
                    launches_mod.align_by_day_offset(sales.get("by_day", []), start)
                    if not isinstance(sales, Exception) else []
                ),
            }
        except Exception as e:
            return {"id": L["id"], "name": L["name"], "error": str(e)}

    series = await asyncio.gather(*[_series(L) for L in [current] + others])
    return {"current": series[0], "previous": series[1:]}


@router.get("/launches/{launch_id}/pace")
async def launch_pace(launch_id: str, user: dict = Depends(get_current_user)):
    """Forecast where the launch will land by close, based on previous-launch ratios."""
    current = await db.launches.find_one({"id": launch_id}, {"_id": 0})
    if not current:
        raise HTTPException(404, "Launch not found")
    all_launches = await db.launches.find({}, {"_id": 0}).sort("start_date", -1).to_list(50)
    previous = [
        L for L in all_launches
        if L["id"] != launch_id and L.get("start_date", "") < current["start_date"]
    ][:3]
    return await launches_mod.compute_pace(db, current, previous)
