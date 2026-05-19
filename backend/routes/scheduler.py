"""Scheduler audit routes — view recent runs of any wrapped cron job.

Lets us answer 'did the 19:00 interview-eve job fire last night?' without
having to dig through Render logs. Records live in db.scheduler_runs and
are written by scheduler_audit.run_audited.
"""
from fastapi import APIRouter, Depends

from db import db
from deps import require_admin

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/runs")
async def list_runs(
    admin: dict = Depends(require_admin),
    job_id: str | None = None,
    limit: int = 50,
):
    """Recent scheduler runs (newest first), optionally filtered to one
    job_id. Each row has started_at, finished_at, duration_ms, status, and
    either `result` (on success) or `error` (on failure)."""
    query: dict = {}
    if job_id:
        query["job_id"] = job_id
    rows = await db.scheduler_runs.find(
        query, {"_id": 0},
    ).sort("started_at", -1).limit(min(max(1, limit), 200)).to_list(200)
    return {"runs": rows, "total": len(rows), "filter": {"job_id": job_id}}


@router.get("/runs/by-job")
async def runs_by_job(admin: dict = Depends(require_admin)):
    """One row per known job_id with the most recent run's status. Useful
    for an at-a-glance 'which jobs are healthy' overview."""
    pipeline = [
        {"$sort": {"started_at": -1}},
        {"$group": {
            "_id": "$job_id",
            "last_started_at": {"$first": "$started_at"},
            "last_status": {"$first": "$status"},
            "last_duration_ms": {"$first": "$duration_ms"},
            "last_result": {"$first": "$result"},
            "last_error": {"$first": "$error"},
        }},
        {"$sort": {"last_started_at": -1}},
    ]
    rows = await db.scheduler_runs.aggregate(pipeline).to_list(None)
    for r in rows:
        r["job_id"] = r.pop("_id")
    return {"jobs": rows}
