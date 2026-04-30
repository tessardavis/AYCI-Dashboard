"""Scorecard: metrics CRUD + weekly values + auto-compute endpoint."""
from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse

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



# -- CSV export -------------------------------------------------------------
def _format_csv_value(value, fmt):
    """Format a metric value for CSV. None → empty cell."""
    if value is None:
        return ""
    if fmt == "currency":
        return f"{float(value):.2f}"
    if fmt == "percentage":
        return f"{float(value):.1f}"
    return str(value)


@router.get("/scorecard/export.csv")
async def scorecard_export_csv(
    scope: str = "year",
    weeks: int = 8,
    user: dict = Depends(require_board("weekly_scorecard")),
):
    """CSV export of the weekly scorecard.

    Query params:
      - scope=year   (default) — every recorded week for every metric
      - scope=recent — last `weeks` weeks (default 8) only
    Each row: Category, Metric, Goal, Format, then one column per week.
    """
    if scope not in ("year", "recent"):
        raise HTTPException(400, "scope must be 'year' or 'recent'")
    metrics = await db.metrics.find({}, {"_id": 0}).sort([("category", 1), ("order", 1)]).to_list(1000)
    weekly_values = await db.weekly_values.find({}, {"_id": 0}).to_list(100000)

    # Build {metric_id: {week_start: value}}
    by_metric: dict[str, dict[str, float]] = {}
    all_weeks: set[str] = set()
    for wv in weekly_values:
        by_metric.setdefault(wv["metric_id"], {})[wv["week_start"]] = wv["value"]
        all_weeks.add(wv["week_start"])
    weeks_sorted = sorted(all_weeks)

    if scope == "recent":
        today = datetime.now(timezone.utc).date()
        this_monday = today - timedelta(days=today.weekday())
        cutoff = (this_monday - timedelta(weeks=max(1, int(weeks)) - 1)).isoformat()
        weeks_sorted = [w for w in weeks_sorted if w >= cutoff]

    # Build CSV rows
    import csv
    import io
    buf = io.StringIO()
    writer = csv.writer(buf)
    header = ["Category", "Metric", "Format", "Goal"] + weeks_sorted
    writer.writerow(header)
    for m in metrics:
        row = [
            m.get("category", ""),
            m.get("name", ""),
            m.get("format", ""),
            _format_csv_value(m.get("goal"), m.get("format", "number")),
        ]
        values = by_metric.get(m["id"], {})
        for w in weeks_sorted:
            row.append(_format_csv_value(values.get(w), m.get("format", "number")))
        writer.writerow(row)

    today_iso = datetime.now(timezone.utc).date().isoformat()
    filename = f"ayci-scorecard-{scope}-{today_iso}.csv"
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
