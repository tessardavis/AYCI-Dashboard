"""Student Lookup, name search, at-risk dashboard, drive summary."""
import asyncio
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Awaitable, Optional

from fastapi import APIRouter, Depends, HTTPException

import student_lookup as lookup
import google_drive as gdrive
import at_risk as at_risk_mod
import tally_lookup as tally

from db import db
from deps import require_board

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["students"])

# Per-platform wall-clock budgets. One stuck call must not block the
# whole page - without these, a hung Tally/Calendly pagination loop
# would block the endpoint until the frontend gives up at 90s.
PLATFORM_TIMEOUTS = {
    "circle":     12.0,  # 1.7MB Mongo read from Atlas - 5s was too tight
    "convertkit": 10.0,  # subscriber lookup + tags (2 sequential calls)
    "stripe":     15.0,  # customer search + parallel charges/subs per customer
    "calendly":   12.0,
    "tally":      15.0,  # multi-MB Mongo cache read
    "monday":     15.0,  # server-side search; sometimes slow GraphQL
}


async def _bounded_platform(
    name: str,
    coro: Awaitable[Any],
    budget: float,
) -> dict:
    """Run a single platform lookup with a wall-clock budget and timing log."""
    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(coro, timeout=budget)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.info(f"[lookup] {name} ok in {elapsed_ms}ms")
        if isinstance(result, dict):
            return result
        return {"found": False, "data": None, "error": "unexpected_shape"}
    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.warning(f"[lookup] {name} TIMEOUT after {elapsed_ms}ms (budget {budget}s)")
        return {"found": False, "data": None, "error": f"{name}_timeout"}
    except Exception as e:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.warning(f"[lookup] {name} failed in {elapsed_ms}ms: {e}")
        return {"found": False, "data": None, "error": str(e)}


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
    failure - the user-facing endpoint will retry/show the error."""
    try:
        await gdrive.summarise_student_doc(db, student_name, email)
    except Exception:
        pass


async def _run_lookup_fanout(
    email: str,
    name: Optional[str] = None,
    *,
    skip_drive_summary: bool = False,
) -> dict:
    """Pure lookup fan-out without auth/HTTP wrapping. Returns the same shape
    as the GET /students/lookup endpoint. Reused by the cache pre-warm cron
    so private-tier students are hot before the team starts the day.

    `skip_drive_summary=True` disables the background Drive summary
    pre-generation (Claude API call). Used by the daily prewarm cron to
    keep costs at $0/day - summaries still generate on-demand when the
    coach opens the doc card."""
    monday_safe, circle_safe, stripe_safe, ck_safe, calendly_safe, tally_safe = await asyncio.gather(
        _bounded_platform("monday",     lookup.monday_lookup(email, name_hint=name, db=db), PLATFORM_TIMEOUTS["monday"]),
        _bounded_platform("circle",     lookup.circle_lookup(db, email),                     PLATFORM_TIMEOUTS["circle"]),
        _bounded_platform("stripe",     lookup.stripe_lookup(email),                         PLATFORM_TIMEOUTS["stripe"]),
        _bounded_platform("convertkit", lookup.convertkit_lookup(email),                     PLATFORM_TIMEOUTS["convertkit"]),
        _bounded_platform("calendly",   lookup.calendly_lookup(email),                       PLATFORM_TIMEOUTS["calendly"]),
        _bounded_platform("tally",      tally.lookup_student(db, email),                     PLATFORM_TIMEOUTS["tally"]),
    )
    # Students often book Calendly / pay Stripe under a DIFFERENT email than the
    # one we searched. Retry those two under any known alternate emails - the
    # student's circle_email + any recorded `other_emails` - and merge in a hit.
    md = (monday_safe or {}).get("data") or {}
    alt_emails: list[str] = []
    for raw in [md.get("circle_email")] + re.split(r"[,\s;]+", md.get("other_emails") or ""):
        e = (raw or "").strip().lower()
        if e and "@" in e and e != email and e not in alt_emails:
            alt_emails.append(e)
    if alt_emails:
        async def _retry(platform: str, current: dict, make_coro):
            """If `current` came back not-found, retry the platform under each
            alternate email and return the first hit (tagged with which email)."""
            if (current or {}).get("found"):
                return current
            for ae in alt_emails:
                r = await _bounded_platform(platform, make_coro(ae), PLATFORM_TIMEOUTS[platform])
                if (r or {}).get("found"):
                    r["matched_email"] = ae
                    return r
            return current

        # Run the four platform retries concurrently - they're independent, so
        # there's no reason to pay calendly+stripe+circle+tally serially when a
        # student has alternate emails (the common mismatch case).
        calendly_safe, stripe_safe, circle_safe, tally_safe = await asyncio.gather(
            _retry("calendly", calendly_safe, lambda ae: lookup.calendly_lookup(ae)),
            _retry("stripe", stripe_safe, lambda ae: lookup.stripe_lookup(ae)),
            _retry("circle", circle_safe, lambda ae: lookup.circle_lookup(db, ae)),
            _retry("tally", tally_safe, lambda ae: tally.lookup_student(db, ae)),
        )

    drive_link = None
    drive_summary = None
    student_name = (monday_safe.get("data") or {}).get("name") if monday_safe else None
    if student_name:
        # Bound the Drive call - it has no internal timeout and has been
        # observed hanging the whole lookup endpoint when the Drive API is
        # slow. Cap at 10s; on timeout return a 'not found' so the rest of
        # the page still renders.
        try:
            drive_link = await asyncio.wait_for(
                gdrive.find_student_doc_link(db, student_name),
                timeout=10,
            )
        except asyncio.TimeoutError:
            drive_link = {"found": False, "error": "drive_lookup_timeout"}
        except Exception as e:
            drive_link = {"found": False, "error": str(e)}
        # The inline summary read is a Mongo query so it should be fast, but
        # cap it too to be safe.
        try:
            drive_summary = await asyncio.wait_for(
                _get_inline_summary(email),
                timeout=5,
            )
        except asyncio.TimeoutError:
            drive_summary = None
        if (drive_link or {}).get("found") and not drive_summary and not skip_drive_summary:
            asyncio.create_task(_prewarm_drive_summary(student_name, email))

    return {
        "email": email,
        "monday": monday_safe,
        "circle": circle_safe,
        "stripe": stripe_safe,
        "convertkit": ck_safe,
        "calendly": calendly_safe,
        "tally": tally_safe,
        "drive": drive_link,
        "drive_summary": drive_summary,
    }


# Student Lookup is hit repeatedly during a coaching session (coaches re-open
# the same student to copy a link, check a date, etc). Cache the full
# fan-out for 30 minutes per email so 2nd/3rd opens are instant. The 05:30 UK
# pre-warm job populates this for every private-tier student before the team
# starts the day.
LOOKUP_CACHE_TTL_MINUTES = 30


async def _read_lookup_cache(email: str) -> Optional[dict]:
    doc = await db.student_lookup_cache.find_one({"_id": email}, {"_id": 0})
    if not doc:
        return None
    cached_at = doc.get("cached_at")
    if isinstance(cached_at, datetime):
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOOKUP_CACHE_TTL_MINUTES)
        if cached_at > cutoff:
            payload = doc.get("payload") or {}
            payload["_cached"] = True
            payload["_cached_at"] = cached_at.isoformat()
            return payload
    return None


async def _write_lookup_cache(email: str, payload: dict) -> None:
    try:
        # Drop any inline-cached flags before persisting so subsequent reads
        # don't double-flag.
        clean = {k: v for k, v in payload.items() if not k.startswith("_")}
        await db.student_lookup_cache.update_one(
            {"_id": email},
            {"$set": {
                "_id": email,
                "payload": clean,
                "cached_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
    except Exception:
        pass


@router.get("/students/lookup")
async def students_lookup(
    email: str,
    name: Optional[str] = None,
    refresh: bool = False,
    user: dict = Depends(require_board("students")),
):
    """Unified student lookup - fan out across Monday.com, Circle, Stripe,
    ConvertKit, Calendly, Tally in parallel. Optional `name` param falls
    back to a Monday name-column search when emails differ across platforms.
    Pass `refresh=true` to bypass the 30-min cache and force a fresh fetch."""
    if not email or "@" not in email:
        raise HTTPException(400, "Valid email required")
    email = email.strip().lower()

    # Bound each phase so a slow Mongo or stuck fan-out can't hang the route
    # past the frontend's 90s ceiling. Timing is logged so we can see in
    # Render logs which phase is the bottleneck for a given request.
    req_t0 = time.monotonic()
    if not refresh:
        try:
            cached = await asyncio.wait_for(_read_lookup_cache(email), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning(f"[lookup] cache_read TIMEOUT for {email}")
            cached = None
        cache_ms = int((time.monotonic() - req_t0) * 1000)
        if cached:
            logger.info(f"[lookup] {email} cache HIT in {cache_ms}ms")
            return cached
        logger.info(f"[lookup] {email} cache MISS ({cache_ms}ms), running fan-out")

    fanout_t0 = time.monotonic()
    try:
        payload = await asyncio.wait_for(
            _run_lookup_fanout(email, name=name),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        fanout_ms = int((time.monotonic() - fanout_t0) * 1000)
        logger.error(f"[lookup] {email} fan-out TIMEOUT after {fanout_ms}ms")
        raise HTTPException(504, "Lookup timed out - try again in a moment")
    fanout_ms = int((time.monotonic() - fanout_t0) * 1000)
    logger.info(f"[lookup] {email} fan-out done in {fanout_ms}ms")

    try:
        await asyncio.wait_for(_write_lookup_cache(email, payload), timeout=3.0)
    except asyncio.TimeoutError:
        logger.warning(f"[lookup] cache_write TIMEOUT for {email}")

    total_ms = int((time.monotonic() - req_t0) * 1000)
    logger.info(f"[lookup] {email} TOTAL {total_ms}ms")
    return payload


@router.patch("/students/lookup/{monday_item_id}")
async def students_lookup_update(
    monday_item_id: str,
    body: dict,
    user: dict = Depends(require_board("students")),
):
    """Update a student's name on the Monday Academy Members board. Used by
    the Student Lookup header pencil-edit so coaches can fix typos / add
    missing surnames inline. Busts caches so the change is immediately
    visible across the dashboard."""
    new_name = (body or {}).get("name", "").strip()
    if not new_name or len(new_name) < 2:
        raise HTTPException(400, "Name must be at least 2 characters")
    if len(new_name) > 80:
        raise HTTPException(400, "Name too long (max 80 chars)")

    import student_edit as edit_mod
    result = await edit_mod.update_student_name(db, monday_item_id, new_name)
    return result


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
