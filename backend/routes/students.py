"""Student Lookup, name search, at-risk dashboard, drive summary."""
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

import student_lookup as lookup
import google_drive as gdrive
import at_risk as at_risk_mod
import tally_lookup as tally

from db import db
from deps import require_board

router = APIRouter(prefix="/api", tags=["students"])


async def _get_inline_summary(email: str) -> Optional[dict]:
    """If a fresh AI summary is already cached for this student, return it so
    the Student Lookup page can render it inline (no extra round-trip)."""
    if not email:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=gdrive.SUMMARY_TTL_HOURS)
    cached = await db.drive_doc_summaries.find_one(
        {"_id": email.strip().lower()}, {"_id": 0}
    )
    if not cached:
        return None
    ca = cached.get("cached_at")
    if isinstance(ca, datetime):
        if ca.tzinfo is None:
            ca = ca.replace(tzinfo=timezone.utc)
        if ca > cutoff:
            return {**cached, "cached": True}
    return None


async def _prewarm_drive_summary(student_name: str, email: str) -> None:
    """Background task fired on every Student Lookup so by the time the user
    clicks the doc card the AI summary is already in the DB cache. Silent on
    failure — the user-facing endpoint will retry/show the error."""
    try:
        await gdrive.summarise_student_doc(db, student_name, email)
    except Exception:
        pass


@router.get("/students/lookup")
async def students_lookup(
    email: str,
    name: Optional[str] = None,
    user: dict = Depends(require_board("students")),
):
    """Unified student lookup — fan out across Monday.com, Circle, Stripe,
    ConvertKit, Calendly, Tally in parallel. Optional `name` param falls
    back to a Monday name-column search when emails differ across platforms."""
    if not email or "@" not in email:
        raise HTTPException(400, "Valid email required")
    email = email.strip().lower()
    monday_t, circle_t, stripe_t, ck_t, calendly_t, tally_t = await asyncio.gather(
        lookup.monday_lookup(email, name_hint=name),
        lookup.circle_lookup(db, email),
        lookup.stripe_lookup(email),
        lookup.convertkit_lookup(email),
        lookup.calendly_lookup(email),
        tally.lookup_student(db, email),
        return_exceptions=True,
    )

    def _safe(result):
        if isinstance(result, Exception):
            return {"found": False, "data": None, "error": str(result)}
        return result

    monday_safe = _safe(monday_t)
    drive_link = None
    drive_summary = None
    student_name = (monday_safe.get("data") or {}).get("name") if monday_safe else None
    if student_name:
        try:
            drive_link = await gdrive.find_student_doc_link(db, student_name)
        except Exception as e:
            drive_link = {"found": False, "error": str(e)}
        # If we already have a fresh AI summary cached, return it inline so the
        # PrivateDocCard renders instantly instead of triggering a 2nd request.
        drive_summary = await _get_inline_summary(email)
        # If found a doc but no fresh summary yet, kick off the summary fetch
        # in the background so it's hot the moment the coach clicks the card.
        if (drive_link or {}).get("found") and not drive_summary:
            asyncio.create_task(_prewarm_drive_summary(student_name, email))

    return {
        "email": email,
        "monday": monday_safe,
        "circle": _safe(circle_t),
        "stripe": _safe(stripe_t),
        "convertkit": _safe(ck_t),
        "calendly": _safe(calendly_t),
        "tally": _safe(tally_t),
        "drive": drive_link,
        "drive_summary": drive_summary,
    }


@router.get("/students/name-search")
async def students_name_search(
    q: str, limit: int = 10,
    user: dict = Depends(require_board("students")),
):
    return await lookup.name_search(db, q, limit=limit)


@router.post("/students/circle-cache/refresh")
async def circle_cache_refresh(user: dict = Depends(require_board("students"))):
    await db.circle_members_cache.delete_one({"_id": "all"})
    members, source = await lookup._circle_get_cached_members(db)
    return {"refreshed": True, "source": source, "member_count": len(members)}


@router.get("/students/drive-summary")
async def students_drive_summary(
    email: str, name: str,
    user: dict = Depends(require_board("students")),
):
    return await gdrive.summarise_student_doc(db, name, email)


@router.get("/students/drive-diagnostic")
async def students_drive_diagnostic(
    user: dict = Depends(require_board("students")),
):
    """Returns how many files the configured Drive service account can see
    in the private-tier folder. Useful when prod lookups silently return
    'not found' due to folder-share or env-var drift."""
    try:
        files = await gdrive._list_docs()
        return {
            "ok": True,
            "files_seen": len(files),
            "sample": [{"name": f["name"], "modifiedTime": f.get("modifiedTime")} for f in files[:5]],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/students/drive-cache/clear")
async def students_drive_cache_clear(
    name: str = "",
    user: dict = Depends(require_board("students")),
):
    """Bust the per-student Drive lookup cache. With ?name=Foo Bar clears just
    that student; without it clears every cached link. Also busts the in-process
    folder-list cache so the next call sees newly-shared docs."""
    gdrive._bust_doc_list_cache()
    if name:
        key = f"drive_link:{gdrive._normalise(name)}"
        result = await db.cache.delete_one({"_id": key})
        # Also bust the summary cache (keyed by email or normalised name)
        await db.drive_doc_summaries.delete_many(
            {"_id": {"$regex": f"^{gdrive._normalise(name).replace(' ', '.*')}"}}
        )
        return {"cleared": result.deleted_count, "scope": "single", "name": name}
    result = await db.cache.delete_many({"_id": {"$regex": "^drive_link:"}})
    await db.drive_doc_summaries.delete_many({})
    return {"cleared": result.deleted_count, "scope": "all"}


@router.get("/students/at-risk")
async def students_at_risk(
    refresh: bool = False,
    user: dict = Depends(require_board("at_risk")),
):
    if refresh:
        asyncio.create_task(at_risk_mod.warm_at_risk_cache(db, force=True))
    payload = await at_risk_mod.get_at_risk_cached(db, force=False)
    if payload.get("computing") or payload.get("stale"):
        asyncio.create_task(at_risk_mod.warm_at_risk_cache(db, force=False))
    return payload
