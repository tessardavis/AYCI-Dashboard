"""Cohort labels + summary."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import cohort as cohort_mod
import settings_store

from db import db
from deps import require_board, require_admin

router = APIRouter(prefix="/api", tags=["cohorts"])

# --- "Still to join Circle" follow-up tracker -----------------------------
# Coralie logs each time she contacts a pending student (email / DM / reminder /
# call / other) so the chase list shows how many times + when they were last
# contacted - to avoid duplicate reminders and spot who's due a phone call.
# Stored one doc per student email so it survives the cached summary recompute.
_CONTACTS = "circle_join_contacts"
_CONTACT_CHANNELS = {"email", "dm", "reminder", "call", "other"}


class ContactLogBody(BaseModel):
    email: str
    channel: str = "other"
    note: Optional[str] = None


def _contact_summary(doc: dict | None) -> dict:
    events = (doc or {}).get("contacts") or []
    return {
        "contact_count": len(events),
        "last_contacted_at": events[-1]["at"] if events else None,
        "contacts": events,
    }


async def _attach_contacts(payload: dict) -> dict:
    """Overlay the follow-up log onto the pending list at serve time, so a newly
    logged contact shows immediately even though the summary itself is cached."""
    try:
        rows = (((payload or {}).get("circle") or {}).get("pending") or {}).get("list") or []
    except AttributeError:
        return payload
    if not rows:
        return payload
    emails = [(r.get("email") or "").strip().lower() for r in rows if r.get("email")]
    by_email: dict[str, dict] = {}
    async for doc in db[_CONTACTS].find({"_id": {"$in": emails}}):
        by_email[doc["_id"]] = doc
    for r in rows:
        r.update(_contact_summary(by_email.get((r.get("email") or "").strip().lower())))
    return payload


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
        return await _attach_contacts(await _compute())
    key = f"cohort_summary:{cohort.strip().lower()}"
    if force:
        payload = await _compute()
        await db[launches_mod._FN_CACHE].update_one(
            {"_id": key},
            {"$set": {"payload": payload, "cached_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        return await _attach_contacts(payload)
    payload = await launches_mod._stale_while_revalidate(
        db, key, ttl_min=10, compute_fn=_compute,
    )
    return await _attach_contacts(payload)


@router.post("/cohorts/circle-join/contact")
async def log_circle_join_contact(
    body: ContactLogBody,
    user: dict = Depends(require_board("cohort")),
):
    """Log one follow-up with a 'Still to join Circle' student. Appends a timestamped
    event; returns the updated count + history for that student."""
    email = (body.email or "").strip().lower()
    if not email:
        raise HTTPException(400, "email required")
    channel = (body.channel or "other").strip().lower()
    if channel not in _CONTACT_CHANNELS:
        channel = "other"
    event = {
        "at": datetime.now(timezone.utc).isoformat(),
        "channel": channel,
        "note": (body.note or "").strip() or None,
        "by": user.get("email") or "dashboard",
    }
    await db[_CONTACTS].update_one(
        {"_id": email}, {"$push": {"contacts": event}}, upsert=True)
    doc = await db[_CONTACTS].find_one({"_id": email})
    return {"ok": True, "email": email, **_contact_summary(doc)}


@router.post("/cohorts/circle-join/contact/undo")
async def undo_circle_join_contact(
    body: ContactLogBody,
    user: dict = Depends(require_board("cohort")),
):
    """Remove the most recent logged contact for a student (fat-finger undo)."""
    email = (body.email or "").strip().lower()
    if not email:
        raise HTTPException(400, "email required")
    await db[_CONTACTS].update_one({"_id": email}, {"$pop": {"contacts": 1}})
    doc = await db[_CONTACTS].find_one({"_id": email})
    return {"ok": True, "email": email, **_contact_summary(doc)}
