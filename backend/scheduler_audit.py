"""
Scheduler audit + Slack heartbeat.

Wraps any async scheduler job in `run_audited(db, job_id, fn)` so that:
  - Every run writes a doc to `db.scheduler_runs` (started_at, finished_at,
    duration_ms, status='ok'|'failed', result|error). Queryable history
    without having to dig through Render logs.
  - Failures (exceptions raised inside `fn`) post a Slack alert via
    SLACK_WEBHOOK_URL and re-raise.
  - Successes optionally post a one-line Slack heartbeat with the result
    summary — useful for daily jobs where you want confirmation it fired.

Indexed lookups: callers query `db.scheduler_runs.find({"job_id": X}).sort("started_at", -1)`.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import httpx

logger = logging.getLogger(__name__)

_SLACK_TIMEOUT = 10


def _webhook_url() -> Optional[str]:
    url = (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()
    return url or None


async def _slack_post(text: str) -> None:
    url = _webhook_url()
    if not url:
        logger.info("[scheduler-audit] SLACK_WEBHOOK_URL not set — skipping Slack ping")
        return
    try:
        async with httpx.AsyncClient(timeout=_SLACK_TIMEOUT) as c:
            r = await c.post(url, json={"text": text})
            r.raise_for_status()
    except Exception as e:
        logger.warning(f"[scheduler-audit] Slack post failed: {e}")


async def run_audited(
    db,
    job_id: str,
    fn: Callable[[], Awaitable[Any]],
    *,
    announce_success: bool = False,
    announce_summary_keys: Optional[list[str]] = None,
) -> Any:
    """
    Run `fn` and record an audit doc to `db.scheduler_runs`.

    On exception: writes status='failed' with the error, pings Slack, re-raises.
    On success: writes status='ok' with the result. Success is silent by
    default — the dashboard surfaces the audit history. Set
    `announce_success=True` for jobs where you want a Slack heartbeat every
    run. `announce_summary_keys` controls which keys from a dict result get
    included in the heartbeat.
    """
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    await db.scheduler_runs.insert_one({
        "id": run_id,
        "job_id": job_id,
        "started_at": started_at.isoformat(),
        "status": "running",
    })

    try:
        result = await fn()
    except Exception as e:
        finished_at = datetime.now(timezone.utc)
        await db.scheduler_runs.update_one(
            {"id": run_id},
            {"$set": {
                "finished_at": finished_at.isoformat(),
                "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
                "status": "failed",
                "error": str(e)[:2000],
                "error_type": type(e).__name__,
            }},
        )
        await _slack_post(
            f":rotating_light: Scheduler job *{job_id}* FAILED\n"
            f"`{type(e).__name__}: {str(e)[:500]}`"
        )
        raise

    finished_at = datetime.now(timezone.utc)
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    stored_result = result if isinstance(result, dict) else {"return": str(result)[:1000]}
    await db.scheduler_runs.update_one(
        {"id": run_id},
        {"$set": {
            "finished_at": finished_at.isoformat(),
            "duration_ms": duration_ms,
            "status": "ok",
            "result": stored_result,
        }},
    )

    if announce_success:
        if isinstance(result, dict):
            if announce_summary_keys:
                summary_parts = [
                    f"{k}={result.get(k)}" for k in announce_summary_keys
                    if k in result
                ]
            else:
                summary_parts = [f"{k}={v}" for k, v in result.items()]
            summary = " · ".join(summary_parts) if summary_parts else "(no summary)"
        else:
            summary = str(result)[:200]
        await _slack_post(
            f":white_check_mark: Scheduler job *{job_id}* ran in {duration_ms} ms — {summary}"
        )

    return result
