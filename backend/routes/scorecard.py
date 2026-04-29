"""Scorecard: metrics CRUD + weekly values + auto-compute endpoint."""
from datetime import datetime
from typing import List

from fastapi import APIRouter, Body, Depends, HTTPException

import scorecard_auto
import launches as launches_mod

from db import db
from deps import get_current_user, require_admin, require_board
from models import (
    Metric, MetricCreate, MetricUpdate,
    WeeklyValue, WeeklyValueInput,
)

router = APIRouter(prefix="/api", tags=["scorecard"])


# -- Metrics ----------------------------------------------------------------
@router.get("/metrics", response_model=List[Metric])
async def list_metrics(user: dict = Depends(get_current_user)):
    return await db.metrics.find({}, {"_id": 0}).sort("order", 1).to_list(1000)


@router.post("/metrics", response_model=Metric)
async def create_metric(data: MetricCreate, admin: dict = Depends(require_admin)):
    count = await db.metrics.count_documents({})
    m = Metric(**data.model_dump(), order=count)
    await db.metrics.insert_one(m.model_dump())
    return m


@router.patch("/metrics/reorder")
async def reorder_metrics(
    payload: dict = Body(..., example={"order": [{"id": "metric-id", "order": 0}]}),
    admin: dict = Depends(require_admin),
):
    """Admin-only: bulk-update the `order` field of multiple metrics.
    Payload: `{"order": [{"id": "<metric_id>", "order": 0}, ...]}`. Used by
    the drag-and-drop reorder UI in Settings → Metrics."""
    items = payload.get("order")
    if not isinstance(items, list):
        raise HTTPException(400, "Payload must be {\"order\": [{id, order}...]}")
    updated = 0
    for item in items:
        mid = item.get("id")
        order = item.get("order")
        if not mid or order is None:
            continue
        res = await db.metrics.update_one({"id": mid}, {"$set": {"order": int(order)}})
        if res.modified_count:
            updated += 1
    return {"ok": True, "updated": updated}


@router.patch("/metrics/{metric_id}", response_model=Metric)
async def update_metric(metric_id: str, data: MetricUpdate, admin: dict = Depends(require_admin)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        await db.metrics.update_one({"id": metric_id}, {"$set": updates})
    doc = await db.metrics.find_one({"id": metric_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return doc


@router.delete("/metrics/{metric_id}")
async def delete_metric(metric_id: str, admin: dict = Depends(require_admin)):
    await db.metrics.delete_one({"id": metric_id})
    await db.weekly_values.delete_many({"metric_id": metric_id})
    return {"ok": True}


# -- Weekly values ----------------------------------------------------------
@router.get("/scorecard/auto-compute")
async def scorecard_auto_compute(
    week_start: str,
    user: dict = Depends(require_board("weekly_scorecard")),
):
    """Auto-compute derived weekly metrics from external APIs.
    `week_start` must be ISO date (YYYY-MM-DD, a Monday). Cached 60 min."""
    try:
        ws = datetime.fromisoformat(week_start).date()
    except ValueError:
        raise HTTPException(400, "week_start must be ISO date (YYYY-MM-DD)")
    cache_key = f"scorecard_auto:{ws.isoformat()}"

    async def _compute():
        return await scorecard_auto.auto_compute_all(db, ws)

    return await launches_mod._stale_while_revalidate(
        db, cache_key, ttl_min=60, compute_fn=_compute,
    )


@router.get("/weekly-values")
async def list_weekly_values(user: dict = Depends(get_current_user)):
    return await db.weekly_values.find({}, {"_id": 0}).to_list(100000)


@router.post("/weekly-values")
async def upsert_weekly_value(data: WeeklyValueInput, user: dict = Depends(get_current_user)):
    existing = await db.weekly_values.find_one(
        {"metric_id": data.metric_id, "week_start": data.week_start}
    )
    if existing:
        await db.weekly_values.update_one(
            {"metric_id": data.metric_id, "week_start": data.week_start},
            {"$set": {"value": data.value}},
        )
        return {
            "id": existing["id"],
            "metric_id": data.metric_id,
            "week_start": data.week_start,
            "value": data.value,
        }
    wv = WeeklyValue(
        metric_id=data.metric_id, week_start=data.week_start, value=data.value
    )
    await db.weekly_values.insert_one(wv.model_dump())
    return wv.model_dump()
