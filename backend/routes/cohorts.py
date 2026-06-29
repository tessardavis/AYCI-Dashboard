"""Cohort labels + summary."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

import cohort as cohort_mod
import settings_store

from db import db
from deps import require_board, require_admin

router = APIRouter(prefix="/api", tags=["cohorts"])


@router.get("/cohorts/labels")
async def cohort_labels(user: dict = Depends(require_board("cohort"))):
    """Returns the list of cohort labels from Monday's 'Cohort Joined' dropdown."""
    return await cohort_mod.fetch_cohort_labels()


@router.get("/cohorts/config")
async def get_cohort_config(user: dict = Depends(require_board("cohort"))):
    """Per-cohort dashboard config: {cohort_label: {circle_tag, new_tag_id,
    legacy_tag_id, intros_space_id}}. Editable in Settings so each launch is a
    config change, not a deploy."""
    return await settings_store.get_cohort_configs(db)


@router.put("/cohorts/config")
async def put_cohort_config(payload: dict, admin: dict = Depends(require_admin)):
    """Replace the per-cohort config map. Accepts {"configs": {...}} or the
    bare map."""
    configs = payload.get("configs") if isinstance(payload, dict) and "configs" in payload else payload
    try:
        return await settings_store.set_cohort_configs(db, configs)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/cohorts/summary")
async def cohort_summary_endpoint(
    cohort: str = "April 26",
    circle_tag: Optional[str] = None,
    new_tag_id: Optional[int] = None,
    legacy_tag_id: Optional[int] = None,
    intros_space_id: Optional[int] = None,
    force: bool = False,
    user: dict = Depends(require_board("cohort")),
):
    """Aggregated cohort stats. New / Legacy counts come from ConvertKit tags
    (authoritative). Circle cross-reference uses the cached members list.

    Cached ~10 min stale-while-revalidate so the page loads instantly after the
    first compute - the live Monday+Circle aggregation (the slow part) only runs
    on a cold cache or `?force=true` (the Refresh button)."""
    import launches as launches_mod
    from datetime import datetime, timezone

    async def _compute():
        return await cohort_mod.cohort_summary(
            db, cohort, circle_tag=circle_tag, new_tag_id=new_tag_id,
            legacy_tag_id=legacy_tag_id, intros_space_id=intros_space_id,
        )

    # Only cache the plain call shape (no explicit overrides) - that's what the
    # dashboard sends; ad-hoc overrides bypass the cache and compute live.
    cacheable = (circle_tag is None and new_tag_id is None
                 and legacy_tag_id is None and intros_space_id is None)
    if not cacheable:
        return await _compute()
    key = f"cohort_summary:{cohort.strip().lower()}"
    if force:
        payload = await _compute()
        await db[launches_mod._FN_CACHE].update_one(
            {"_id": key},
            {"$set": {"payload": payload, "cached_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        return payload
    return await launches_mod._stale_while_revalidate(
        db, key, ttl_min=10, compute_fn=_compute,
    )
