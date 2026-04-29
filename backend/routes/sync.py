"""External-source sync (ConvertKit, Stripe, etc.)."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import connectors
from db import db
from deps import get_current_user, require_admin
from models import WeeklyValue

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["sync"])


def _monday_of_date(iso_date: str) -> str:
    from datetime import date as _date
    y, m, d = [int(x) for x in iso_date.split("-")]
    d_obj = _date(y, m, d)
    return (d_obj - timedelta(days=d_obj.weekday())).isoformat()


@router.get("/sync/discover")
async def sync_discover(admin: dict = Depends(require_admin)):
    """Return picker options (shows/tags/spaces/boards) for Settings UI."""
    return await connectors.discover()


@router.get("/sync/connectors")
async def sync_connectors(user: dict = Depends(get_current_user)):
    return sorted(connectors.CONNECTORS.keys())


class SyncRequest(BaseModel):
    week_start: Optional[str] = None
    overwrite: bool = False


@router.post("/sync/run")
async def sync_run(req: SyncRequest, user: dict = Depends(get_current_user)):
    if req.week_start:
        week_start = _monday_of_date(req.week_start)
    else:
        today = datetime.now(timezone.utc).date()
        this_monday = today - timedelta(days=today.weekday())
        week_start = (this_monday - timedelta(days=7)).isoformat()
    start_dt = datetime.fromisoformat(week_start + "T00:00:00+00:00")
    end_dt = start_dt + timedelta(days=6, hours=23, minutes=59, seconds=59)
    start_iso = start_dt.isoformat().replace("+00:00", "Z")
    end_iso = end_dt.isoformat().replace("+00:00", "Z")

    metrics = await db.metrics.find({"source_type": {"$ne": None}}, {"_id": 0}).to_list(1000)
    results = []
    for m in metrics:
        source_type = m.get("source_type")
        if not source_type:
            continue
        try:
            value = await connectors.pull_value(
                source_type, m.get("source_params") or {}, start_iso, end_iso
            )
            existing = await db.weekly_values.find_one(
                {"metric_id": m["id"], "week_start": week_start}
            )
            if existing and not req.overwrite:
                results.append({
                    "metric_id": m["id"], "name": m["name"], "value": existing.get("value"),
                    "pulled": value, "written": False, "reason": "existing value preserved",
                })
                continue
            if existing:
                await db.weekly_values.update_one(
                    {"metric_id": m["id"], "week_start": week_start},
                    {"$set": {"value": value}},
                )
            else:
                wv = WeeklyValue(metric_id=m["id"], week_start=week_start, value=value)
                await db.weekly_values.insert_one(wv.model_dump())
            results.append({
                "metric_id": m["id"], "name": m["name"], "value": value,
                "pulled": value, "written": True,
            })
        except Exception as e:
            logger.warning(f"Sync failed for metric {m.get('name')}: {e}")
            results.append({
                "metric_id": m["id"], "name": m["name"], "error": str(e), "written": False,
            })
    return {
        "week_start": week_start,
        "window": {"start": start_iso, "end": end_iso},
        "total_metrics_with_source": len(metrics),
        "results": results,
    }
