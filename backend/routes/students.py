"""Student Lookup, name search, at-risk dashboard, drive summary."""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

import student_lookup as lookup
import google_drive as gdrive
import at_risk as at_risk_mod
import tally_lookup as tally

from db import db
from deps import require_board

router = APIRouter(prefix="/api", tags=["students"])


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
    student_name = (monday_safe.get("data") or {}).get("name") if monday_safe else None
    if student_name:
        try:
            drive_link = await gdrive.find_student_doc_link(db, student_name)
        except Exception as e:
            drive_link = {"found": False, "error": str(e)}

    return {
        "email": email,
        "monday": monday_safe,
        "circle": _safe(circle_t),
        "stripe": _safe(stripe_t),
        "convertkit": _safe(ck_t),
        "calendly": _safe(calendly_t),
        "tally": _safe(tally_t),
        "drive": drive_link,
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
    that student; without it clears every cached link."""
    if name:
        key = f"drive_link:{gdrive._normalise(name)}"
        result = await db.cache.delete_one({"_id": key})
        return {"cleared": result.deleted_count, "scope": "single", "name": name}
    result = await db.cache.delete_many({"_id": {"$regex": "^drive_link:"}})
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
