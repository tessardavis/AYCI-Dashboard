"""
CRUD over the Academy Members Mongo mirror — the data set that eventually
fully replaces the Monday Academy Members board.

Reads pull from db.academy_members (the 15-min mirror). Writes update the
same row AND mark the edited field in `dashboard_edited_fields` so the
next Monday sync doesn't clobber the change.

Routes:
  GET   /api/students-db                  list, with filters + search
  GET   /api/students-db/{monday_item_id} one row
  PATCH /api/students-db/{monday_item_id} update fields (protected from sync)
  POST  /api/students-db/update-by-email  Zapier-callable lookup+update
                                          (replaces Monday Get Items + Update Item)
  POST  /api/students-db/intake           Zapier-callable upsert for new
                                          signups (Kajabi/Tally/waitlist)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timezone, timedelta, date
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from db import db
from deps import require_board, require_admin
import webhooks_outbound

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["students-db"])


# CURRENT private products that get set up (private chat + allowance). Used for
# the "needs setup" flag. Deliberately a positive allow-list so deprecated/old
# tiers (Platinum, Academy/Upgrade 1:1, Gold/Platinum Legacy Upgrade) are NOT
# flagged — confirmed with Tessa 2026-06-06.
_CURRENT_PRIVATE_TIERS = {
    "academy private plus", "upgrade private plus", "private plus",
    "vip", "upgrade vip",
    "boost & go", "boost & go plus",
}


def _is_current_private_tier(tier: Optional[str]) -> bool:
    parts = [p.strip() for p in (tier or "").lower().split(",") if p.strip()]
    return any(p in _CURRENT_PRIVATE_TIERS for p in parts)


def _b_and_g_active(boost: Optional[str]) -> bool:
    """The 'Boost + Go' column carries customer states — B&G / B&G Plus /
    B&G - Presentation / B&G Plus - Presentation, plus 'Upgraded' (they did
    buy B&G; confirmed by Tessa) — and sales-pipeline states (Offer Due/Made/
    Declined) which are NOT paying customers."""
    b = (boost or "").strip().lower()
    return "b&g" in b or b == "upgraded"


# Expected private video allowance per tier / Boost & Go level (Tessa, 2026-06-06).
_VIDEO_ALLOWANCE_BY_TIER = {
    "academy private plus": 15, "upgrade private plus": 15, "private plus": 15,
    "vip": 30, "upgrade vip": 30,
    "boost & go": 5, "boost & go plus": 10,
}


def expected_video_allowance(tier: Optional[str], boost: Optional[str]) -> Optional[int]:
    """Expected private video allowance, or None if the tier/B&G doesn't have a
    defined allowance (e.g. base Academy, or 1:1/Platinum — not yet specified)."""
    t = (tier or "").strip().lower()
    if t in _VIDEO_ALLOWANCE_BY_TIER:
        return _VIDEO_ALLOWANCE_BY_TIER[t]
    b = (boost or "").strip().lower()
    if "b&g" in b or b == "upgraded":
        return 10 if "plus" in b else 5
    return None


def _is_boss(row: dict) -> bool:
    """Boss Badge = Yes → they've landed their job and are finished working with
    us, so they need no further setup (private chat / allowance)."""
    return (row.get("boss_badge") or "").strip().lower() in {"yes", "true", "1", "y"}


def _allowance_flag(row: dict) -> Optional[str]:
    """'missing' (expected but unset), 'mismatch' (set but ≠ expected),
    'ok', or None (no expected allowance defined, or student is a Boss)."""
    if _is_boss(row):
        return None
    exp = expected_video_allowance(row.get("tier"), row.get("boost_and_go"))
    if exp is None:
        return None
    cur = row.get("video_allowance")
    if cur in (None, ""):
        return "missing"
    try:
        return "ok" if int(cur) == exp else "mismatch"
    except (TypeError, ValueError):
        return "mismatch"


def _private_chat_blocked(row: dict) -> bool:
    """A non-empty `private_chat_status` is a pending note (e.g. "Awaiting DMs",
    written by the chat zap when the student has DMs switched off). Its presence
    means setup is blocked/pending — surface the student in "Needs setup" even if
    a (dead) chat URL exists. Cleared once the chat is actually working."""
    return bool((row.get("private_chat_status") or "").strip())


def _needs_private_chat_setup(row: dict) -> bool:
    """True for a private-tier / active Boost & Go student who still needs
    setting up — i.e. missing their private chat link, blocked on a pending
    status (e.g. awaiting DMs), OR missing their video allowance. (A
    wrong-but-present allowance is a 'mismatch', surfaced separately, not
    auto-changed.)"""
    if row.get("setup_not_needed"):
        return False  # manually dismissed — intentionally fine to leave empty
    if _is_boss(row):
        return False  # landed their job — finished with us, no setup needed
    if not (_is_current_private_tier(row.get("tier")) or _b_and_g_active(row.get("boost_and_go"))):
        return False
    no_chat = not (row.get("private_chat_url") or "").strip()
    return no_chat or _private_chat_blocked(row) or _allowance_flag(row) == "missing"


_MONTHS = {}
for _i, _m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1):
    _MONTHS[_m] = _i
    _MONTHS[_m[:3]] = _i


def _parse_loose_date(text: str, default_year: int) -> Optional[date]:
    """Best-effort parse of a free-text interview date. Handles ISO
    (2026-07-19), d/m or d/m/y, '19th July [2026]', 'July 19'. Returns a date
    or None for vague text ('soon', 'July', 'TBC') — None means 'show the raw
    text and let a human judge', never a wrong guess. `default_year` (the
    cohort cutoff's year) fills in a missing year."""
    if not text:
        return None
    t = str(text).strip().lower()
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?\b", t)
    if m:
        yr = int(m.group(3)) if m.group(3) else default_year
        if yr < 100:
            yr += 2000
        try:
            return date(yr, int(m.group(2)), int(m.group(1)))  # UK d/m order
        except ValueError:
            pass
    yr_m = re.search(r"\b(20\d{2})\b", t)
    yr = int(yr_m.group(1)) if yr_m else default_year
    # "<day> <month>" or "<month> <day>"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\b", t)
    if m and (m.group(2) in _MONTHS or m.group(2)[:3] in _MONTHS):
        mon = _MONTHS.get(m.group(2)) or _MONTHS.get(m.group(2)[:3])
        try:
            return date(yr, mon, int(m.group(1)))
        except (ValueError, TypeError):
            pass
    m = re.search(r"\b([a-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\b", t)
    if m and (m.group(1) in _MONTHS or m.group(1)[:3] in _MONTHS):
        mon = _MONTHS.get(m.group(1)) or _MONTHS.get(m.group(1)[:3])
        try:
            return date(yr, mon, int(m.group(2)))
        except (ValueError, TypeError):
            pass
    return None


def _early_interview_flag(kajabi_date: str, cutoff_iso: Optional[str]) -> Optional[str]:
    """'before' / 'after' / 'unparsed' / None for the early-access triage.
    'before' = interview on/before the cohort cutoff (→ candidate for early
    access). 'unparsed' = there's a date string we couldn't read (show raw)."""
    raw = (kajabi_date or "").strip()
    if not raw or not cutoff_iso:
        return None
    try:
        cutoff = date.fromisoformat(cutoff_iso)
    except ValueError:
        return None
    parsed = _parse_loose_date(raw, cutoff.year)
    if not parsed:
        return "unparsed"
    return "before" if parsed <= cutoff else "after"


def _slim_row_for_list(row: dict) -> dict:
    """Drop heavy fields (full column dicts) from list responses."""
    keep = (
        "_id", "name", "first_name", "surname", "email", "circle_email",
        "tier", "cohort_joined", "interview_date", "speciality", "hospital",
        "interview_type", "private_chat_url", "private_chat_status",
        "boost_and_go", "video_allowance",
        "setup_not_needed", "setup_not_needed_reason", "coach_notes",
        "private_chat_last_error",
        "kajabi_interview_date", "early_access_grant", "early_access_granted_at",
        "url", "synced_at", "dashboard_edited_fields",
    )
    out = {k: row.get(k) for k in keep if k in row}
    out["needs_setup"] = _needs_private_chat_setup(row)
    out["video_allowance_expected"] = expected_video_allowance(row.get("tier"), row.get("boost_and_go"))
    out["allowance_flag"] = _allowance_flag(row)
    return out


@router.get("/students-db")
async def list_students(
    q: Optional[str] = None,
    tier: Optional[str] = None,
    cohort: Optional[str] = None,
    has_interview: Optional[bool] = None,
    refunded: Optional[bool] = None,
    early_interview: Optional[bool] = None,
    limit: int = 500,
    user: dict = Depends(require_board("students")),
):
    """Paginated list of Academy Members rows.

    Filters:
      q              substring match against name + email (case-insensitive)
      tier           exact tier text (e.g. "Platinum"). Mongo regex if you
                     need a prefix-style filter — coaches send full strings
                     today though.
      cohort         exact cohort text (e.g. "April 26")
      has_interview  true → only rows with a non-empty interview_date

    Sorted by interview_date asc (rows with no date last)."""
    query: dict = {}
    if tier:
        query["tier"] = tier
    if cohort:
        query["cohort_joined"] = cohort
    if has_interview is True:
        query["interview_date"] = {"$ne": None, "$exists": True}
    elif has_interview is False:
        query["$or"] = [{"interview_date": None}, {"interview_date": {"$exists": False}}]
    if q:
        rx = {"$regex": q, "$options": "i"}
        # Don't smash the broader query with $or — use $and to keep filters
        existing_or = query.pop("$or", None)
        text_or = [
            {"name": rx},
            {"email": rx},
            {"first_name": rx},
            {"surname": rx},
        ]
        if existing_or:
            query["$and"] = [{"$or": existing_or}, {"$or": text_or}]
        else:
            query["$or"] = text_or

    cursor = (
        db.academy_members
        .find(query, {"columns_by_id": 0, "columns": 0})  # heavy fields excluded
        .sort([("interview_date", 1), ("name", 1)])
        # Cap high enough to return the whole board in one page — the slim
        # projection keeps rows small. The old 2000 cap silently dropped
        # students past it (board is ~2.1k), so they couldn't be searched.
        .limit(min(limit, 10000))
    )
    # How many private videos each student has actually submitted (their
    # "used" count) — one aggregation over the submissions collection, keyed by
    # the (lowercased) email it was submitted under.
    used_counts: dict[str, int] = {}
    try:
        async for g in db.private_video_submissions.aggregate(
            [{"$group": {"_id": "$email", "n": {"$sum": 1}}}]
        ):
            em = (g.get("_id") or "")
            if em:
                used_counts[str(em).strip().lower()] = g.get("n", 0)
    except Exception as e:
        logger.info(f"[students-db] videos-used aggregate skipped: {e}")

    # Refunds, keyed by the (lowercased) email the refund was recorded under.
    # One aggregation → a per-email {count, total} map so we can badge rows
    # without a query each. Drives the "Refunded" badge + filter; full detail
    # lives on the Refunds board.
    refund_by_email: dict[str, dict] = {}
    try:
        async for g in db.refunds.aggregate([
            {"$group": {"_id": "$student_email",
                        "count": {"$sum": 1},
                        "total": {"$sum": {"$ifNull": ["$amount", 0]}}}}
        ]):
            em = (g.get("_id") or "")
            if em:
                refund_by_email[str(em).strip().lower()] = {
                    "count": g.get("count", 0),
                    "total": round(g.get("total", 0) or 0, 2),
                }
    except Exception as e:
        logger.info(f"[students-db] refunds aggregate skipped: {e}")

    # Circle-presence index (lowercased email → member) from the slim member
    # cache (cached in-process ~30 min, so this is cheap). Lets the needs-setup
    # view show whether a student is actually ON Circle: a "not on Circle" row
    # is almost always a wrong/typo'd email or a non-joiner (→ fix the email or
    # chase them), vs "on Circle, just needs a chat created".
    circle_email_index: dict = {}
    try:
        import private_chat_setup
        circle_email_index = await private_chat_setup._build_email_index()
    except Exception as e:
        logger.info(f"[students-db] circle email index skipped: {e}")

    # Per-cohort early-access cutoffs, to flag students whose Kajabi interview
    # date falls on/before their cohort's Week-3 cutoff (course catch-up).
    cohort_cutoffs: dict = {}
    try:
        import settings_store
        for _lbl, _cfg in (await settings_store.get_cohort_configs(db)).items():
            cut = (_cfg or {}).get("early_access_cutoff")
            if cut:
                cohort_cutoffs[_lbl.strip().lower()] = cut
    except Exception as e:
        logger.info(f"[students-db] cohort cutoffs skipped: {e}")

    rows = []
    async for r in cursor:
        slim = _slim_row_for_list(r)
        em = (r.get("email") or "").strip().lower()
        ce = (r.get("circle_email") or "").strip().lower()
        # Only meaningful for rows the team still has to action.
        if slim.get("needs_setup") and circle_email_index:
            slim["on_circle"] = bool(
                (em and em in circle_email_index) or (ce and ce in circle_email_index)
            )
        # Early-interview triage flag (course catch-up access).
        if r.get("kajabi_interview_date"):
            cut = cohort_cutoffs.get((r.get("cohort_joined") or "").strip().lower())
            slim["early_interview_flag"] = _early_interview_flag(r.get("kajabi_interview_date"), cut)
        slim["videos_used"] = used_counts.get(em) or used_counts.get(ce) or 0
        rinfo = refund_by_email.get(em) or refund_by_email.get(ce)
        slim["has_refund"] = bool(rinfo)
        slim["refund_count"] = (rinfo or {}).get("count", 0)
        slim["refund_total"] = (rinfo or {}).get("total", 0)
        if refunded is True and not slim["has_refund"]:
            continue
        # Early-interview filter: rows whose interview is before the cutoff OR
        # whose date we couldn't parse (so they still get a human look).
        if early_interview is True and slim.get("early_interview_flag") not in ("before", "unparsed"):
            continue
        rows.append(slim)
    return {"items": rows, "count": len(rows)}


# Declared BEFORE /students-db/{monday_item_id} so the static paths aren't
# shadowed by the id route (Starlette matches in declaration order).
@router.get("/students-db/allowance-audit")
async def allowance_audit(user: dict = Depends(require_board("students"))):
    """Private/B&G students whose video allowance is MISSING or MISMATCHED vs
    the expected per-tier value (PP 15, VIP 30, B&G 5, B&G Plus 10)."""
    missing, mismatch = [], []
    async for r in db.academy_members.find({}, {"columns": 0, "columns_by_id": 0}):
        flag = _allowance_flag(r)
        if flag not in ("missing", "mismatch"):
            continue
        entry = {
            "id": r["_id"], "name": r.get("name"), "email": r.get("email"),
            "tier": r.get("tier"), "boost_and_go": r.get("boost_and_go"),
            "current": r.get("video_allowance"),
            "expected": expected_video_allowance(r.get("tier"), r.get("boost_and_go")),
        }
        (missing if flag == "missing" else mismatch).append(entry)
    missing.sort(key=lambda x: (x.get("name") or ""))
    mismatch.sort(key=lambda x: (x.get("name") or ""))
    return {"missing": missing, "mismatch": mismatch,
            "counts": {"missing": len(missing), "mismatch": len(mismatch)}}


@router.post("/students-db/apply-expected-allowances")
async def apply_expected_allowances(user: dict = Depends(require_board("students"))):
    """Set video_allowance = expected for every student whose allowance is
    MISSING (only). Never overwrites a present value — mismatches are left for
    review. Pins video_allowance as dashboard-owned so the sync won't clobber."""
    now = datetime.now(timezone.utc)
    applied = []
    async for r in db.academy_members.find({}, {"columns": 0, "columns_by_id": 0}):
        if _allowance_flag(r) != "missing":
            continue
        exp = expected_video_allowance(r.get("tier"), r.get("boost_and_go"))
        if exp is None:
            continue
        new_protected = sorted(set(r.get("dashboard_edited_fields") or []) | {"video_allowance"})
        await db.academy_members.update_one(
            {"_id": r["_id"]},
            {"$set": {
                "video_allowance": exp,
                "dashboard_edited_fields": new_protected,
                "dashboard_edited_at": now,
                "dashboard_edited_by": user.get("email") or "dashboard",
            }},
        )
        applied.append({"id": r["_id"], "name": r.get("name"), "set_to": exp})
    return {"ok": True, "set": len(applied), "applied": applied[:300]}


@router.post("/students-db/revert-applied-allowances")
async def revert_applied_allowances(user: dict = Depends(require_board("students"))):
    """Undo a recent apply-expected-allowances: for rows this user set in the
    last 6h where video_allowance still equals the expected value, clear it
    back to empty and un-pin it (so it shows as 'missing' again, exactly as
    before). Only touches the auto-applied ones — never manual edits to other
    values."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    actor = user.get("email") or user.get("id")
    now = datetime.now(timezone.utc)
    reverted = []
    async for r in db.academy_members.find(
        {"dashboard_edited_fields": "video_allowance"},
        {"columns": 0, "columns_by_id": 0},
    ):
        ea = r.get("dashboard_edited_at")
        if not isinstance(ea, datetime):
            continue
        if ea.tzinfo is None:
            ea = ea.replace(tzinfo=timezone.utc)
        if ea < cutoff or (r.get("dashboard_edited_by") != actor):
            continue
        exp = expected_video_allowance(r.get("tier"), r.get("boost_and_go"))
        if exp is None or r.get("video_allowance") != exp:
            continue  # not an untouched auto-applied value — leave it
        new_protected = sorted(set(r.get("dashboard_edited_fields") or []) - {"video_allowance"})
        await db.academy_members.update_one(
            {"_id": r["_id"]},
            {"$set": {
                "video_allowance": None,
                "dashboard_edited_fields": new_protected,
                "dashboard_edited_at": now,
                "dashboard_edited_by": actor,
            }},
        )
        reverted.append({"id": r["_id"], "name": r.get("name"), "was": exp})
    return {"ok": True, "reverted": len(reverted), "items": reverted[:300]}


# Declared BEFORE /students-db/{monday_item_id} so it isn't shadowed by the
# id route (Starlette matches in declaration order).
@router.get("/students-db/intake-recent")
async def intake_recent(
    days: int = 7,
    limit: int = 200,
    user: dict = Depends(require_board("students")),
):
    """Diagnostic: which students arrived via the Zapier `intake` endpoint.

    Confidence check before retiring the Monday "Create Item" steps — open
    this in the browser and confirm recent real signups are landing in the
    dashboard directly.

    Intake stamps `dashboard_edited_by="zapier-intake"` on every row it
    touches and gives brand-new students an `_id` of `auto:<uuid>` until the
    Monday row syncs and `_reconcile_auto_rows` merges them. So:

      - `pending_reconcile` rows (`_id` starts with `auto:`) = created by
        intake, no Monday counterpart synced yet. During the transition these
        should clear within ~15 min; a pile-up of old ones means reconcile or
        the Monday-create path is wedged.
      - non-auto intake rows = intake updated an existing row, OR an auto row
        already reconciled onto its Monday twin.

    `window` counts cover the last `days`; `pending_total` counts ALL
    unreconciled auto rows regardless of age (stragglers surface even if old)."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(days, 0))

    # Everything intake has touched in the window, newest first. Keyed off the
    # durable `intake_seen_at` stamp (carried onto the Monday row at reconcile),
    # NOT dashboard_edited_by — that marker dies with the auto: row, so it would
    # miss every already-reconciled signup.
    cursor = (
        db.academy_members
        .find(
            {"intake_seen_at": {"$gte": cutoff}},
            {"columns": 0, "columns_by_id": 0},
        )
        .sort([("intake_seen_at", -1)])
        .limit(min(limit, 1000))
    )
    recent, created_in_window = [], 0
    async for r in cursor:
        is_auto = str(r.get("_id", "")).startswith("auto:")
        if is_auto:
            created_in_window += 1
        sa = r.get("intake_seen_at")
        ca = r.get("created_at")
        recent.append({
            "id": r["_id"],
            "pending_reconcile": is_auto,
            "name": r.get("name"),
            "email": r.get("email"),
            "tier": r.get("tier"),
            "cohort_joined": r.get("cohort_joined"),
            "source": r.get("source"),
            "intake_seen_at": sa.isoformat() if isinstance(sa, datetime) else sa,
            "created_at": ca.isoformat() if isinstance(ca, datetime) else ca,
        })

    # All-time unreconciled auto rows (not just the window) — a straggler that
    # never found a Monday row would otherwise hide once it ages out.
    pending_total = await db.academy_members.count_documents(
        {"_id": {"$regex": "^auto:"}}
    )

    return {
        "as_of": now.isoformat(),
        "window_days": days,
        "counts": {
            "intake_touched_in_window": len(recent),
            "created_in_window": created_in_window,
            "pending_reconcile_total": pending_total,
        },
        "recent": recent,
    }


# Declared BEFORE /students-db/{monday_item_id} so it isn't shadowed.
@router.get("/students-db/circle-email-gaps")
async def circle_email_gaps(
    user: dict = Depends(require_board("students")),
):
    """Find private-tier students we likely FAILED to link to their Circle
    identity because they joined Circle under a different email than they
    signed up with on Kajabi.

    This is the root cause of "private chats never got created": the upstream
    automation matches the new Circle member back to the student by email, so
    if the Circle email ≠ the Kajabi email, the match fails, `circle_email`
    never gets written, and nothing downstream (group chat, DMs) ever fires.

    Scans current private-tier / active B&G students (not Boss, not
    setup-dismissed) whose `circle_email` is blank, then tries to find them in
    the cached Circle member list. Buckets each:

      - `likely_mismatch`  — a strong NAME match exists in Circle under a
        DIFFERENT email (and their Kajabi email isn't in Circle). The dual-email
        case: almost certainly the same person — copy the Circle email onto
        `circle_email` to link them. Surfaced with both emails + match score.
      - `email_in_circle`  — their Kajabi email IS a Circle member, we just
        never copied it to `circle_email`. Benign (lookups already match on
        either email) but trivially fixable.
      - `not_on_circle`    — no name or email hit. Genuinely not on Circle yet,
        so a chat legitimately can't be created.

    Read-only diagnostic — writes nothing."""
    import student_lookup as lookup

    # All Circle member emails, for the cheap "is their Kajabi email on Circle"
    # check (the slim cache is the same list name_search fuzzy-matches over).
    members = await lookup._get_name_index(db)
    circle_emails = {
        (m.get("email") or "").strip().lower()
        for m in members
        if (m.get("email") or "").strip()
    }

    likely_mismatch, email_in_circle, not_on_circle = [], [], []
    scanned = 0

    async for r in db.academy_members.find({}, {"columns": 0, "columns_by_id": 0}):
        # Same population the "needs setup" flag cares about, minus the chat/
        # allowance test — here the gate is specifically a blank circle_email.
        if r.get("setup_not_needed") or _is_boss(r):
            continue
        if not (_is_current_private_tier(r.get("tier")) or _b_and_g_active(r.get("boost_and_go"))):
            continue
        if (r.get("circle_email") or "").strip():
            continue  # already linked

        scanned += 1
        kajabi_email = (r.get("email") or "").strip().lower()
        base = {
            "id": r["_id"],
            "name": r.get("name"),
            "tier": r.get("tier"),
            "boost_and_go": r.get("boost_and_go"),
            "kajabi_email": kajabi_email or None,
            "has_chat": bool((r.get("private_chat_url") or "").strip()),
        }

        if kajabi_email and kajabi_email in circle_emails:
            email_in_circle.append(base)
            continue

        # No email hit — try a fuzzy name match against the Circle cache.
        hits = await lookup.name_search(db, r.get("name") or "", limit=1) if r.get("name") else []
        top = hits[0] if hits else None
        if top and (top.get("match_score") or 0) >= 80 and (top.get("email") or "").strip():
            likely_mismatch.append({
                **base,
                "circle_name": top.get("name"),
                "circle_email": (top.get("email") or "").strip().lower(),
                "match_score": top.get("match_score"),
            })
        else:
            not_on_circle.append(base)

    likely_mismatch.sort(key=lambda x: (-(x.get("match_score") or 0), x.get("name") or ""))
    email_in_circle.sort(key=lambda x: x.get("name") or "")
    not_on_circle.sort(key=lambda x: x.get("name") or "")

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "scanned_private_no_circle_email": scanned,
            "likely_mismatch": len(likely_mismatch),
            "email_in_circle": len(email_in_circle),
            "not_on_circle": len(not_on_circle),
        },
        "likely_mismatch": likely_mismatch,
        "email_in_circle": email_in_circle,
        "not_on_circle": not_on_circle,
    }


# --- Private-chat setup (Route 2, Phase 0). See PRIVATE_CHAT_MIGRATION.md ---
# Declared BEFORE /students-db/{monday_item_id} so the static paths aren't
# shadowed by the id route.
@router.get("/students-db/private-chat/config")
async def get_private_chat_config(user: dict = Depends(require_board("students"))):
    import settings_store
    return await settings_store.get_private_chat_config(db)


@router.post("/students-db/private-chat/config")
async def set_private_chat_config(request: Request, admin: dict = Depends(require_admin)):
    import settings_store
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")
    try:
        return await settings_store.set_private_chat_config(db, body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/students-db/private-chat/preview")
async def private_chat_preview(user: dict = Depends(require_board("students"))):
    """Dry run — private-tier students who'd get a chat, matched on either
    email. Writes nothing."""
    import private_chat_setup
    return await private_chat_setup.preview(db)


@router.get("/students-db/private-chat/no-chat-audit")
async def private_chat_no_chat_audit(user: dict = Depends(require_board("students"))):
    """Reconciliation audit: current private-tier students with no coach group
    chat in Circle (checks Circle directly, catches dead-URL cases). Read-only."""
    import private_chat_setup
    return await private_chat_setup.no_chat_audit(db)


def _to_dt(v) -> Optional[datetime]:
    """Coerce a Mongo/ISO date value to an aware datetime, or None."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v.strip():
        try:
            dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


@router.get("/students-db/private-chat/maintenance")
async def private_chat_maintenance(
    clear_awaiting: bool = False,
    recent_days: Optional[int] = None,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """Pure-DB backlog + flag maintenance — NO Circle reads (so it never hits the
    Circle rate-limit/timeout that breaks the link-existing scan).

      - `missing_url`: eligible (current private tier OR active B&G) students with no
        private_chat_url — the backlog of chats created before the zaps wrote URLs back.
      - `missing_url_recent`: subset whose monday_created_at (proxy for "joined") is
        within `recent_days` — the likely-genuine gaps (e.g. chats that failed during
        the Coralie-in-list bug). Only returned when `?recent_days=N` is set.
      - `stale_awaiting`: students still carrying an 'Awaiting DMs'-style
        private_chat_status (left over from the now-deleted DMs-off zap branch).
      - `other_status`: students with some OTHER non-empty status — surfaced, NOT
        cleared, so nothing meaningful is wiped silently.
      - `?clear_awaiting=true` blanks the status ONLY on the stale_awaiting set.

    Auth: X-Webhook-Secret (ZAPIER_WEBHOOK_SECRET)."""
    _check_webhook_secret(x_webhook_secret)
    missing_url, stale_awaiting, other_status = [], [], []
    async for r in db.academy_members.find({}, {"columns": 0, "columns_by_id": 0}):
        if not (_is_current_private_tier(r.get("tier")) or _b_and_g_active(r.get("boost_and_go"))):
            continue
        email = (r.get("email") or "").strip().lower() or None
        circle_email = (r.get("circle_email") or "").strip().lower() or None
        status = (r.get("private_chat_status") or "").strip()
        joined = _to_dt(r.get("monday_created_at")) or _to_dt(r.get("created_at"))
        base = {"id": r["_id"], "name": r.get("name"), "email": email,
                "circle_email": circle_email, "tier": r.get("tier"),
                "boost_and_go": r.get("boost_and_go"),
                "cohort_joined": r.get("cohort_joined"),
                "joined_at": joined.isoformat() if joined else None}
        if not (r.get("private_chat_url") or "").strip():
            missing_url.append({**base, "status": status or None})
        if status:
            sl = status.lower()
            (stale_awaiting if ("awaiting" in sl or "dms" in sl) else other_status).append(
                {**base, "status": status})
    cleared = 0
    if clear_awaiting and stale_awaiting:
        res = await db.academy_members.update_many(
            {"_id": {"$in": [s["id"] for s in stale_awaiting]}},
            {"$set": {"private_chat_status": ""}},
        )
        cleared = res.modified_count
    for lst in (missing_url, stale_awaiting, other_status):
        lst.sort(key=lambda x: (x.get("name") or "").lower())
    out = {
        "ok": True,
        "counts": {"missing_url": len(missing_url), "stale_awaiting": len(stale_awaiting),
                   "other_status": len(other_status), "cleared": cleared},
        "missing_url": missing_url,
        "stale_awaiting": stale_awaiting,
        "other_status": other_status,
    }
    if recent_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
        recent = [m for m in missing_url
                  if (_to_dt(m.get("joined_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
        recent.sort(key=lambda x: x.get("joined_at") or "", reverse=True)
        out["counts"]["missing_url_recent"] = len(recent)
        out["missing_url_recent"] = recent
    return out


@router.post("/students-db/{monday_item_id}/create-private-chat")
async def create_private_chat(monday_item_id: str, user: dict = Depends(require_board("students"))):
    """Manual trigger: create ONE student's coach group chat (guarded against
    duplicates). Runs in the BACKGROUND and returns immediately — the create does
    several Circle calls (incl. the all-coaches dedup scan) and was exceeding the
    proxy timeout, hanging the button. The outcome lands on the student's row
    (chat URL written, or 'Awaiting DMs' flagged); the UI re-fetches the preview
    to reflect it."""
    import private_chat_setup
    import asyncio as _asyncio

    async def _run():
        try:
            res = await private_chat_setup.create_for_student(db, monday_item_id)
            # Record any non-success outcome (other than DMs-off, which writes its
            # own status) so nothing fails silently — surfaced as private_chat_last_error.
            if res and not res.get("ok") and res.get("skipped") != "awaiting_dms":
                note = res.get("error") or res.get("skipped") or "create did not complete"
                await db.academy_members.update_one({"_id": monday_item_id}, {"$set": {
                    "private_chat_last_error": str(note)[:300],
                    "private_chat_last_error_at": datetime.now(timezone.utc),
                }})
        except Exception as e:
            import logging
            logging.getLogger("private_chat").exception(f"create_for_student crashed for {monday_item_id}")
            try:
                await db.academy_members.update_one({"_id": monday_item_id}, {"$set": {
                    "private_chat_last_error": f"exception: {type(e).__name__}: {e}"[:300],
                    "private_chat_last_error_at": datetime.now(timezone.utc),
                }})
            except Exception:
                pass

    _asyncio.create_task(_run())
    return {"ok": True, "queued": True, "id": monday_item_id}


_BONUS_CALLS_URL = "https://ayci-academy.circle.so/c/bonus-live-sessions/"


def _early_access_dm(grant: str, first_name: str, prev_name: str,
                     prev_url: str, bonus_url: str) -> str:
    """Build the Circle DM for an early-access grant (sent as the configured
    sender). Mirrors the wording the retired zap #43 used."""
    fn = first_name or "there"
    prev_line = (
        "This is an automated message to let you know that you've been given access to "
        f"the Curriculum space from the {prev_name} cohort.\n"
        f"You can now watch the live session recordings here:\n{prev_url}"
    )
    bonus_line = (
        "You've been given access to our Bonus Live Sessions — the Sunday group coaching "
        f"calls we run between cohorts. You can join them here:\n{bonus_url}"
    )
    parts = [f"Hi {fn},", ""]
    if grant == "previous":
        parts.append(prev_line)
    elif grant == "bonus":
        parts.append(bonus_line)
    else:  # both
        parts.append(prev_line)
        parts.append("")
        parts.append(bonus_line.replace("You've been given", "You've also been given"))
    parts += ["", "Hope that helps!"]
    return "\n".join(parts)


class EarlyAccessGrant(BaseModel):
    grant: str  # "previous" | "bonus" | "both"

    class Config:
        extra = "forbid"


@router.post("/students-db/{monday_item_id}/grant-early-access")
async def grant_early_access(
    monday_item_id: str,
    body: EarlyAccessGrant,
    user: dict = Depends(require_board("students")),
):
    """Give an early-interview student course catch-up access: add them to the
    PREVIOUS cohort's curriculum space and/or the Bonus Live Sessions space,
    then DM them (as the configured sender, e.g. Coralie). Replaces zaps
    #43/#45. `grant` ∈ {previous, bonus, both}. Space IDs + curriculum URL come
    from the student's cohort config (Settings → Cohort)."""
    grant = (body.grant or "").strip().lower()
    if grant not in ("previous", "bonus", "both"):
        raise HTTPException(400, "grant must be 'previous', 'bonus' or 'both'")
    row = await db.academy_members.find_one({"_id": monday_item_id})
    if not row:
        raise HTTPException(404, "Student not found")

    import settings_store
    import circle_api
    configs = await settings_store.get_cohort_configs(db)
    label = (row.get("cohort_joined") or "").strip()
    cfg = configs.get(label) or next(
        (v for k, v in configs.items() if k.strip().lower() == label.lower()), {}
    )
    prev_space = cfg.get("prev_cohort_space_id")
    bonus_space = cfg.get("bonus_calls_space_id")
    prev_url = cfg.get("prev_cohort_curriculum_url") or ""
    prev_name = cfg.get("prev_cohort_name") or "the previous"
    if grant in ("previous", "both") and not prev_space:
        raise HTTPException(400, f"No previous-cohort space configured for cohort '{label}' — set it in Settings → Cohort.")
    if grant in ("bonus", "both") and not bonus_space:
        raise HTTPException(400, f"No bonus-calls space configured for cohort '{label}' — set it in Settings → Cohort.")

    # Resolve the student's Circle member id from the cached member index.
    member = None
    try:
        import private_chat_setup
        idx = await private_chat_setup._build_email_index()
        for cand in ((row.get("circle_email") or "").strip().lower(),
                     (row.get("email") or "").strip().lower()):
            if cand and cand in idx:
                member = idx[cand]
                break
    except Exception as e:
        logger.warning(f"[early-access] member lookup failed for {monday_item_id}: {e}")
    if not member or not member.get("id"):
        raise HTTPException(400, "Student isn't matched on Circle (check their email / that they've joined).")
    member_id = int(member["id"])

    results: dict = {}
    if grant in ("previous", "both"):
        results["previous"] = await circle_api.add_member_to_space(db, int(prev_space), member_id)
    if grant in ("bonus", "both"):
        results["bonus"] = await circle_api.add_member_to_space(db, int(bonus_space), member_id)
    failed = {k: v.get("error") or v.get("status") for k, v in results.items() if not v.get("ok")}
    if failed:
        raise HTTPException(502, f"Couldn't add to space(s): {failed}")

    # DM as the configured sender (e.g. Coralie).
    pcfg = await settings_store.get_private_chat_config(db)
    sender_email = (pcfg.get("sender_email") or "").strip().lower()
    first = (row.get("first_name") or (row.get("name") or "").split(" ")[0] or "").strip()
    dm_sent = False
    if sender_email:
        dm = _early_access_dm(grant, first, prev_name, prev_url, _BONUS_CALLS_URL)
        dm_sent = await circle_api.send_direct_message(db, sender_email, member_id, dm)

    now = datetime.now(timezone.utc)
    pinned = sorted(set(row.get("dashboard_edited_fields") or []) | {"early_access_grant"})
    await db.academy_members.update_one({"_id": monday_item_id}, {"$set": {
        "early_access_grant": grant,
        "early_access_granted_at": now,
        "early_access_granted_by": user.get("email") or user.get("id"),
        "dashboard_edited_fields": pinned,
    }})
    fresh = await db.academy_members.find_one({"_id": monday_item_id}, {"columns": 0, "columns_by_id": 0})
    return {"ok": True, "grant": grant, "spaces": results, "dm_sent": dm_sent,
            "item": _slim_row_for_list(fresh)}


@router.get("/students-db/private-chat/link-existing")
async def private_chat_link_existing(apply: bool = False, refresh: bool = False,
                                     admin: dict = Depends(require_admin)):
    """Backlog fix: find eligible students who ALREADY have a coach group chat in
    Circle but no private_chat_url (e.g. zap-created chats never written back) and
    record the URL. The scan is slow (reads every coach's chats), so it runs in
    the BACKGROUND and caches the result:
      - ?refresh=true  → start a fresh DRY-RUN scan (returns 'started').
      - ?apply=true    → start a scan that WRITES the URLs (returns 'started').
      - no params      → return the last cached result (or kick a first run).
    Re-open with no params ~60s after a refresh/apply to see linked[] + not_found[]."""
    import private_chat_setup
    import asyncio as _asyncio
    if apply or refresh:
        async def _run():
            try:
                await private_chat_setup.link_existing_chats(db, apply=apply)
            except Exception as e:
                import logging
                logging.getLogger("private_chat").exception("link_existing_chats crashed")
                try:  # cache the crash so the plain URL shows it instead of staying blank
                    await db.cache.update_one(
                        {"_id": "private_chat_link_existing"},
                        {"$set": {"cached_at": datetime.now(timezone.utc),
                                  "result": {"ok": False, "error": f"scan crashed: {type(e).__name__}: {e}"[:400]}}},
                        upsert=True,
                    )
                except Exception:
                    pass
        _asyncio.create_task(_run())
        return {"status": f"scan started (apply={apply}) — re-open this URL with NO params in ~60s for the result"}
    cached = await db.cache.find_one({"_id": "private_chat_link_existing"}, {"_id": 0})
    if not cached:
        # Don't auto-kick here — repeated reloads would spawn parallel scans and
        # hammer Circle. Ask for an explicit ?refresh=true.
        return {"status": "no result cached yet — open this URL with ?refresh=true once, wait ~60s, then reload with no params"}
    ca = cached.get("cached_at")
    return {"cached_at": ca.isoformat() if hasattr(ca, "isoformat") else ca, **(cached.get("result") or {})}


@router.get("/students-db/private-chat/debug-coaches")
async def private_chat_debug_coaches(admin: dict = Depends(require_admin)):
    """Diagnostic for the link-existing scan. For each configured coach,
    sequentially mint a Headless session and read page 1 of their group chats,
    reporting the outcome per coach (no email / token mint failed / HTTP status
    / how many group chats). Cheap (1 page each) and gentle (sequential), so it
    pins down WHY the bulk scan returns 'couldn't read any coach group chats' —
    auth failure vs 429 throttle vs genuinely empty — without the heavy 30-page
    fan-out."""
    import settings_store
    import circle_api
    import httpx as _httpx
    cfg = await settings_store.get_private_chat_config(db)
    out = []
    for c in cfg.get("coaches") or []:
        name, email = c.get("name"), (c.get("email") or "").strip()
        entry = {"name": name, "email": email or None}
        if not email:
            entry["result"] = "no_email_configured"
            out.append(entry)
            continue
        token = await circle_api._get_access_token(db, email)
        entry["token_ok"] = bool(token)
        if not token:
            entry["result"] = "token_mint_failed"
            out.append(entry)
            continue
        try:
            async with _httpx.AsyncClient(timeout=20) as cli:
                r = await cli.get(
                    f"{circle_api.HEADLESS_BASE}/messages",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"per_page": 100, "page": 1},
                )
            entry["list_status"] = r.status_code
            if r.status_code == 200:
                body = r.json()
                recs = body.get("records") or []
                entry["records"] = len(recs)
                entry["group_chats"] = sum(1 for x in recs if x.get("chat_room_kind") == "group_chat")
                entry["has_next_page"] = bool(body.get("has_next_page"))
                # Diagnostic: what does a record actually look like, and what
                # kind values exist? (We were filtering on chat_room_kind=="group"
                # and getting 0 — find the real field/value.)
                kinds: dict = {}
                for x in recs:
                    for kf in ("chat_room_kind", "kind", "room_kind", "type"):
                        v = x.get(kf)
                        if v is not None:
                            kinds[f"{kf}={v}"] = kinds.get(f"{kf}={v}", 0) + 1
                entry["kind_values_seen"] = kinds
                if recs:
                    entry["sample_record_keys"] = sorted(recs[0].keys())
            else:
                entry["body"] = (r.text or "")[:200]
        except Exception as e:
            entry["error"] = f"{type(e).__name__}: {e}"[:200]
        out.append(entry)
    return {
        "parent_token_configured": bool(circle_api._headless_parent_token()),
        "sender_email": cfg.get("sender_email"),
        "coaches": out,
    }


@router.get("/students-db/private-chat/auto-create")
async def private_chat_auto_create(limit: int = 25, admin: dict = Depends(require_admin)):
    """HYBRID auto-create (Phase 1): create chats for all clear-cut ready students
    (eligible, on Circle, template set, no chat), flag DMs-off as 'Awaiting DMs',
    and report the judgement cases (no template / not on Circle) for the team.
    Idempotent + guarded. This is the dashboard-native replacement for the Monday
    zaps 46/47/53 — run it on demand to verify, then enable
    PRIVATE_CHAT_AUTOCREATE_ENABLED + turn those zaps OFF."""
    import private_chat_setup
    return await private_chat_setup.auto_create_ready_chats(db, limit=limit)


@router.get("/students-db/{monday_item_id}")
async def get_student(
    monday_item_id: str,
    user: dict = Depends(require_board("students")),
):
    """Full row including the columns dict (used by Student Lookup-style
    full-detail views)."""
    row = await db.academy_members.find_one({"_id": monday_item_id})
    if not row:
        raise HTTPException(404, "Student not found in academy_members mirror")
    return row


# Editable fields from the dashboard. Anything outside this list returns
# a 400 — explicit allowlist prevents accidental edits to fields that
# upstream automations control (e.g. someone PATCHing video_allowance
# when Stripe is supposed to own that).
EDITABLE_FIELDS = {
    "name", "first_name", "surname", "email", "circle_email",
    "tier", "cohort_joined", "interview_date", "speciality", "hospital",
    "interview_type", "private_chat_url", "private_chat_status", "video_allowance",
    "setup_not_needed", "setup_not_needed_reason", "coach_notes", "boost_and_go",
}


class StudentPatch(BaseModel):
    """Each call PATCHes a small subset of fields. Any field present is
    treated as an edit — set explicitly to `null` to clear it."""
    name: Optional[str] = None
    first_name: Optional[str] = None
    surname: Optional[str] = None
    email: Optional[str] = None
    circle_email: Optional[str] = None
    tier: Optional[str] = None
    cohort_joined: Optional[str] = None
    interview_date: Optional[str] = None  # ISO yyyy-mm-dd
    speciality: Optional[str] = None
    hospital: Optional[str] = None
    interview_type: Optional[str] = None
    private_chat_url: Optional[str] = None
    private_chat_status: Optional[str] = None
    video_allowance: Optional[int] = None
    setup_not_needed: Optional[bool] = None
    setup_not_needed_reason: Optional[str] = None
    coach_notes: Optional[str] = None  # free-text team notes (dashboard-only)
    boost_and_go: Optional[str] = None  # e.g. "B&G" / "B&G Plus" — for dual-email fixes

    class Config:
        extra = "forbid"  # reject unknown keys outright


@router.patch("/students-db/{monday_item_id}")
async def update_student(
    monday_item_id: str,
    patch: StudentPatch,
    user: dict = Depends(require_board("students")),
):
    """Update one or more fields on a student row. Edited fields get
    added to `dashboard_edited_fields` so the next 15-min Monday sync
    doesn't overwrite the change."""
    # Only consider fields the caller explicitly set (not Pydantic defaults)
    set_fields = patch.dict(exclude_unset=True)
    if not set_fields:
        raise HTTPException(400, "No fields to update")

    # Allowlist guard (also covered by Pydantic extra=forbid, but defensive)
    bad = set(set_fields.keys()) - EDITABLE_FIELDS
    if bad:
        raise HTTPException(400, f"Fields not editable here: {sorted(bad)}")

    existing = await db.academy_members.find_one({"_id": monday_item_id})
    if not existing:
        raise HTTPException(404, "Student not found in academy_members mirror")

    # Normalise email-ish fields to lowercase (matches the sync logic)
    for k in ("email", "circle_email"):
        if k in set_fields and set_fields[k] is not None:
            set_fields[k] = set_fields[k].strip().lower() or None

    now = datetime.now(timezone.utc)
    update_set: dict[str, Any] = dict(set_fields)
    update_set["dashboard_edited_at"] = now
    update_set["dashboard_edited_by"] = user.get("email") or user.get("id")

    # Union the existing protected-fields list with the newly edited ones.
    new_protected = set(existing.get("dashboard_edited_fields") or [])
    new_protected.update(set_fields.keys())
    update_set["dashboard_edited_fields"] = sorted(new_protected)

    await db.academy_members.update_one(
        {"_id": monday_item_id}, {"$set": update_set}
    )

    fresh = await db.academy_members.find_one({"_id": monday_item_id})

    # Outbound webhook fan-out — fire only for columns whose value actually
    # changed (skip no-op writes). Fire-and-forget so the response isn't
    # blocked on downstream zaps.
    diff = webhooks_outbound.changed_fields_diff(existing, set_fields)
    if diff:
        asyncio.create_task(
            webhooks_outbound.notify_column_changes(
                db, item_id=monday_item_id, fields_changed=diff, student=fresh,
            )
        )

    return fresh


# ----------------------------------------------------- Zapier-callable update
# Replaces the Monday "Get Items by Column Value + Update Item" pair used by
# ~40 zaps. Zap re-point: swap both Monday steps for one Webhooks-by-Zapier
# POST to this endpoint with the email + fields to change.
#
# Auth: shared secret in `X-Webhook-Secret`. Set ZAPIER_WEBHOOK_SECRET on
# Render and paste the same string into each zap's Webhooks step header.

def _check_webhook_secret(x_webhook_secret: Optional[str]) -> None:
    expected = (os.environ.get("ZAPIER_WEBHOOK_SECRET") or "").strip()
    if not expected:
        raise HTTPException(503, "Webhook auth not configured")
    if (x_webhook_secret or "").strip() != expected:
        raise HTTPException(401, "Invalid webhook secret")


def _parse_email_and_fields(body: dict) -> tuple[str, dict]:
    """Accept both nested and flat payload shapes so the Zapier Webhooks
    step is easy to configure:

      Nested (what Postman / a hand-written client sends):
        {"email": "x@y.z", "fields": {"milestone_1": "Yes"}}

      Flat (what's natural in Zapier's key/value UI):
        {"email": "x@y.z", "milestone_1": "Yes"}

    Returns (email, fields_dict)."""
    if not isinstance(body, dict):
        raise HTTPException(400, "payload must be an object")
    email = body.get("email")
    if not isinstance(email, str) or not email.strip():
        raise HTTPException(400, "email is required")
    nested = body.get("fields")
    if isinstance(nested, dict) and nested:
        return email, nested
    # Flat mode: everything except `email` and a small set of reserved
    # top-level keys is treated as a field to set.
    reserved = {"email", "source"}
    flat = {k: v for k, v in body.items() if k not in reserved}
    if not flat:
        raise HTTPException(400, "fields must be non-empty")
    return email, flat


@router.post("/students-db/update-by-email")
async def update_student_by_email(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """Find a student by email (or circle_email) and update fields.

    Returns 404 if no match — zaps' existing Slack-alert fallback paths
    can branch on that response. Returns 400 if any field is not in the
    automation allowlist."""
    _check_webhook_secret(x_webhook_secret)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    email, fields = _parse_email_and_fields(body)
    email_l = email.strip().lower()

    bad = set(fields.keys()) - PROTECTED_FIELDS
    if bad:
        raise HTTPException(
            400, f"Fields not writable by automation: {sorted(bad)}"
        )

    row = await db.academy_members.find_one(
        {"$or": [{"email": email_l}, {"circle_email": email_l}]},
    )
    if not row:
        # Surface as 404 so the zap's existing not-found branch fires.
        raise HTTPException(404, f"No student found for email={email_l}")

    set_fields: dict[str, Any] = dict(fields)
    # Normalise email-ish fields (matches PATCH + mirror behaviour)
    for k in ("email", "circle_email"):
        if k in set_fields and set_fields[k] is not None:
            set_fields[k] = str(set_fields[k]).strip().lower() or None

    # Capture the pre-write values for read-modify-write callers (Zapier
    # filter steps that need the prior value). Empty string for fields not
    # previously set, since Zapier filters treat null awkwardly.
    previous_values = {k: (row.get(k) if row.get(k) is not None else "") for k in set_fields.keys()}

    now = datetime.now(timezone.utc)
    update_set: dict[str, Any] = dict(set_fields)
    update_set["dashboard_edited_at"] = now
    update_set["dashboard_edited_by"] = "zapier"

    new_protected = set(row.get("dashboard_edited_fields") or [])
    new_protected.update(set_fields.keys())
    update_set["dashboard_edited_fields"] = sorted(new_protected)

    await db.academy_members.update_one(
        {"_id": row["_id"]}, {"$set": update_set}
    )
    logger.info(
        f"[students-db] zapier update email={email_l} "
        f"id={row['_id']} fields={list(set_fields.keys())}"
    )

    # Outbound webhook fan-out — diff vs the pre-write row.
    diff = webhooks_outbound.changed_fields_diff(row, set_fields)
    if diff:
        fresh = await db.academy_members.find_one({"_id": row["_id"]})
        asyncio.create_task(
            webhooks_outbound.notify_column_changes(
                db, item_id=row["_id"], fields_changed=diff, student=fresh or row,
            )
        )

    return {
        "ok": True,
        "id": row["_id"],
        "matched_on": "email" if row.get("email") == email_l else "circle_email",
        "updated_fields": sorted(set_fields.keys()),
        "previous_values": previous_values,
    }


# --------------------------------------------- Zapier-callable 1:1 call booking
# Replaces the "1:1 Round Robin" zaps' AI-by-Zapier step that worked out which
# Call slot (1-4) a new booking should fill. The four Call columns on Monday
# are status columns sharing the label set:
#   Eligible | Booked | Booked - Becky | Booked - Tessa
#   Booked - Anoop | Booked - Charlotte
# Rule (confirmed 2026-06-04): fill the lowest-numbered slot whose current
# value is NOT already "Booked..." (i.e. Eligible or blank), with
# "Booked - <Coach>". If all four are booked, write nothing and return
# slot=null so the zap's existing Fallback (Slack alert) path can fire.

# Coaches with a dedicated "Booked - X" status label. Lowercased key → label.
_CALL_COACHES = {
    "becky": "Becky",
    "tessa": "Tessa",
    "anoop": "Anoop",
    "charlotte": "Charlotte",
}


def _current_call_slot(row: dict, n: int) -> str:
    """Current value of Call slot n for this row.

    Prefers the dashboard-owned scalar `call_n`; falls back to the Monday
    column dump (`columns["Call n"].text`) so the rule works during the
    safety-net week before the dashboard owns the field. "" if unset."""
    scalar = row.get(f"call_{n}")
    if scalar is not None:
        return str(scalar)
    entry = (row.get("columns") or {}).get(f"Call {n}")
    if isinstance(entry, dict):
        return entry.get("text") or ""
    return ""


@router.post("/students-db/book-call")
async def book_call(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """Mark a student's next available 1:1 call slot as booked with a coach.

    Body: {"email": "x@y.z", "coach": "Anoop"}

    Returns the slot filled (1-4) and the value written, or slot=null with
    reason="all_slots_booked" when every slot is already taken. 404 if no
    student matches the email."""
    _check_webhook_secret(x_webhook_secret)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    if not isinstance(body, dict):
        raise HTTPException(400, "payload must be an object")
    email = body.get("email")
    if not isinstance(email, str) or not email.strip():
        raise HTTPException(400, "email is required")
    coach_raw = body.get("coach")
    if not isinstance(coach_raw, str) or not coach_raw.strip():
        raise HTTPException(400, "coach is required")
    coach = _CALL_COACHES.get(coach_raw.strip().lower())
    if not coach:
        raise HTTPException(
            400, f"coach must be one of: {sorted(_CALL_COACHES.values())}"
        )
    email_l = email.strip().lower()

    row = await db.academy_members.find_one(
        {"$or": [{"email": email_l}, {"circle_email": email_l}]},
    )
    if not row:
        raise HTTPException(404, f"No student found for email={email_l}")

    matched_on = "email" if row.get("email") == email_l else "circle_email"

    # Lowest-numbered slot not already "Booked..." (Eligible or blank).
    slot = None
    for n in (1, 2, 3, 4):
        if not _current_call_slot(row, n).strip().startswith("Booked"):
            slot = n
            break

    if slot is None:
        logger.info(
            f"[students-db] book-call all slots full email={email_l} id={row['_id']}"
        )
        return {
            "ok": True,
            "id": row["_id"],
            "matched_on": matched_on,
            "slot": None,
            "reason": "all_slots_booked",
        }

    field = f"call_{slot}"
    value = f"Booked - {coach}"
    previous_value = _current_call_slot(row, slot)

    now = datetime.now(timezone.utc)
    new_protected = set(row.get("dashboard_edited_fields") or [])
    new_protected.add(field)
    await db.academy_members.update_one(
        {"_id": row["_id"]},
        {"$set": {
            field: value,
            "dashboard_edited_at": now,
            "dashboard_edited_by": "zapier",
            "dashboard_edited_fields": sorted(new_protected),
        }},
    )
    logger.info(
        f"[students-db] book-call email={email_l} id={row['_id']} "
        f"{field}={value!r} (was {previous_value!r})"
    )

    # Outbound webhook fan-out if the slot value actually changed.
    diff = webhooks_outbound.changed_fields_diff(row, {field: value})
    if diff:
        fresh = await db.academy_members.find_one({"_id": row["_id"]})
        asyncio.create_task(
            webhooks_outbound.notify_column_changes(
                db, item_id=row["_id"], fields_changed=diff, student=fresh or row,
            )
        )

    return {
        "ok": True,
        "id": row["_id"],
        "matched_on": matched_on,
        "slot": slot,
        "field": field,
        "value": value,
        "previous_value": previous_value if previous_value else "",
    }


# ------------------------------------------------- Zapier-callable read/lookup
# The read counterpart to update-by-email. Replaces a Monday "Get Items by
# Column Value + Get Column Values" pair when a zap needs to READ current
# state before deciding what to write (e.g. the 1:1 Round Robin AI step that
# picks which call slot to fill). Writes nothing.

# Heavy fields never returned to a webhook caller — the full Monday column
# dumps are large and not useful to a zap.
_HEAVY_FIELDS = {"columns", "columns_by_id"}


@router.post("/students-db/lookup-by-email")
async def lookup_student_by_email(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """Find a student by email (or circle_email) and return their fields.

    Body:
      {"email": "x@y.z"}                              scalar fields only
      {"email": "x@y.z", "columns": ["1:1 Call 1"]}   also pull these Monday
                                                       column titles by text

    Returns the row's scalar fields (heavy Monday column dumps excluded).
    For each title in `columns`, the current Monday text value is returned
    under `columns[title]` — lets a zap read a column the mirror doesn't
    promote to a scalar yet (e.g. call slots) during the safety-net week.

    404 on no match, mirroring update-by-email so a zap's existing
    not-found branch fires the same way."""
    _check_webhook_secret(x_webhook_secret)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    if not isinstance(body, dict):
        raise HTTPException(400, "payload must be an object")
    email = body.get("email")
    if not isinstance(email, str) or not email.strip():
        raise HTTPException(400, "email is required")
    email_l = email.strip().lower()

    requested_cols = body.get("columns") or []
    if not isinstance(requested_cols, list):
        raise HTTPException(400, "columns must be a list of Monday column titles")

    soft = bool(body.get("soft"))

    row = await db.academy_members.find_one(
        {"$or": [{"email": email_l}, {"circle_email": email_l}]},
    )
    if not row:
        if soft:
            # Soft mode: 200 with found=false instead of 404, so a Zapier
            # Webhooks step can branch on `found` (via Paths) without the step
            # erroring and halting the zap — needed by zaps with a designed
            # "not on board → Slack alert" branch (e.g. New Circle member).
            return {"ok": True, "found": False, "email": email_l}
        raise HTTPException(404, f"No student found for email={email_l}")

    fields = {
        k: v for k, v in row.items()
        if k not in _HEAVY_FIELDS and not isinstance(v, datetime)
    }

    # Pull requested Monday columns by title from the stored dump. Each entry
    # is {"text":..., "type":...}; return the text. "" for a missing title or
    # empty value so a zap filter sees an empty string, not null.
    col_titles = row.get("columns") or {}

    def _col_text(title: str) -> str:
        entry = col_titles.get(title)
        if not isinstance(entry, dict):
            return ""
        return entry.get("text") or ""

    columns_out = {str(title): _col_text(title) for title in requested_cols}

    return {
        "ok": True,
        "found": True,
        "id": row["_id"],
        "matched_on": "email" if row.get("email") == email_l else "circle_email",
        "fields": fields,
        "columns": columns_out,
    }


# --------------------------------------------------- Toolkit access check
# Read endpoint for the toolkit site (tools.medicalinterviewprep.com et al.)
# to gate material access by Kajabi add-on purchase. The dashboard is the
# source of truth: the Kajabi purchase-capture zap sets the addon_* fields
# "Yes" via update-by-email; this endpoint reads them back by email.
#
# Maps each access key (what the toolkit site asks about) to the dashboard
# field. Add new add-ons here + in PROTECTED_FIELDS.
TOOLKIT_ADDONS = {
    "curveball_questions": "addon_curveball_questions",      # £47 order bump (Kajabi 2151209227, Circle delivery)
    "question_sets": "addon_question_sets",                  # 30 Recent Question Sets upsell (Kajabi 2151209222)
    "pre_interview_toolkit": "addon_pre_interview_toolkit",  # £97 upsell (Kajabi 2151209231, tools.medicalinterviewprep.com)
}


def _addon_on(value: Any) -> bool:
    """An add-on flag counts as purchased when set to an affirmative value."""
    return str(value or "").strip().lower() in {"yes", "true", "1", "y"}


@router.post("/toolkit/access")
async def toolkit_access(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """Return which add-ons a student has purchased, by email.

    Body: {"email": "x@y.z"}
    Auth: X-Webhook-Secret (set TOOLKIT_ACCESS_SECRET on Render to use a
    dedicated secret; otherwise falls back to ZAPIER_WEBHOOK_SECRET).

    Always 200 (never 404) so the toolkit site gets a clean allow/deny:
      { "found": true/false,
        "access": { "curveball_questions": bool, "question_sets": bool,
                    "pre_interview_toolkit": bool } }
    A non-existent student returns found=false with all access false."""
    _check_toolkit_secret(x_webhook_secret)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    if not isinstance(body, dict):
        raise HTTPException(400, "payload must be an object")
    email = body.get("email")
    if not isinstance(email, str) or not email.strip():
        raise HTTPException(400, "email is required")
    email_l = email.strip().lower()

    row = await db.academy_members.find_one(
        {"$or": [{"email": email_l}, {"circle_email": email_l}]},
        {"_id": 1, **{f: 1 for f in TOOLKIT_ADDONS.values()}},
    )
    if not row:
        return {
            "email": email_l,
            "found": False,
            "access": {k: False for k in TOOLKIT_ADDONS},
        }
    return {
        "email": email_l,
        "found": True,
        "id": row["_id"],
        "access": {k: _addon_on(row.get(field)) for k, field in TOOLKIT_ADDONS.items()},
    }


def _check_toolkit_secret(x_webhook_secret: Optional[str]) -> None:
    """Accept a dedicated TOOLKIT_ACCESS_SECRET if configured, else fall back
    to the shared ZAPIER_WEBHOOK_SECRET."""
    toolkit = (os.environ.get("TOOLKIT_ACCESS_SECRET") or "").strip()
    if toolkit:
        if (x_webhook_secret or "").strip() == toolkit:
            return
        raise HTTPException(401, "Invalid toolkit secret")
    _check_webhook_secret(x_webhook_secret)


# Re-export so the webhook endpoint can use the same allowlist as the sync.
# Imported lazily to avoid a module-load cycle.
def _protected_fields_set() -> set[str]:
    try:
        from academy_members_mirror import PROTECTED_FIELDS as _PF
        return set(_PF)
    except Exception:
        return EDITABLE_FIELDS

PROTECTED_FIELDS = _protected_fields_set()


# --------------------------------------------------- Zapier-callable intake
# Replaces Monday "Create Item" for new student signups (Kajabi purchases,
# Tally onboarding, waitlist registrations). Upserts on email: existing
# academy_members row → update tier + provided fields; otherwise insert
# a new row with _id="auto:<uuid>".

# Extra fields the intake endpoint can set on a row in addition to the
# normal scalar columns. Tracked so we know who/what created the row.
INTAKE_ONLY_FIELDS = {"stage", "source", "intake_payload_meta", "kajabi_interview_date"}


@router.post("/students-db/intake")
async def intake_student(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """Upsert a student row by email.

    Behaviour:
      - email matches an existing row (by email OR circle_email): update
        the allowlisted fields, preserve dashboard_edited_fields audit
        trail, return action="updated".
      - no match: insert a new row with _id="auto:<uuid>", marked
        synced_from_monday=False so the 15-min Monday sync leaves it alone.
        Return action="created".

    The endpoint deliberately does NOT branch on offer name or do tier
    lookups itself — the zap (or future intake-routing logic) supplies
    `fields.tier` directly. Keeps this endpoint a thin primitive.

    Accepts both nested (`{email, fields:{...}, source}`) and flat
    (`{email, tier, cohort_joined, ..., source}`) payload shapes."""
    _check_webhook_secret(x_webhook_secret)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    email, fields = _parse_email_and_fields(body)
    email_l = email.strip().lower()
    source = body.get("source")

    allowed = PROTECTED_FIELDS | INTAKE_ONLY_FIELDS
    bad = set(fields.keys()) - allowed
    if bad:
        raise HTTPException(
            400, f"Fields not writable by intake: {sorted(bad)}"
        )

    set_fields: dict[str, Any] = dict(fields)
    # Normalise email-ish fields (matches PATCH + mirror behaviour)
    for k in ("email", "circle_email"):
        if k in set_fields and set_fields[k] is not None:
            set_fields[k] = str(set_fields[k]).strip().lower() or None

    # Always carry the lookup email and source through to the row
    set_fields.setdefault("email", email_l)
    if source:
        set_fields["source"] = source

    existing = await db.academy_members.find_one(
        {"$or": [{"email": email_l}, {"circle_email": email_l}]},
        {"_id": 1, "dashboard_edited_fields": 1},
    )

    now = datetime.now(timezone.utc)
    update_set: dict[str, Any] = dict(set_fields)
    update_set["dashboard_edited_at"] = now
    update_set["dashboard_edited_by"] = "zapier-intake"

    # Durable provenance stamp so the intake-recent diagnostic can still see
    # this signup AFTER its auto: row reconciles away (dashboard_edited_by is
    # carried on the auto: row, which reconcile deletes; this survives).
    update_set["intake_seen_at"] = now

    if existing:
        # Update — preserve dashboard_edited_fields audit
        new_protected = set(existing.get("dashboard_edited_fields") or [])
        # Only the scalar columns go in the protected set, not the
        # intake-only metadata fields.
        new_protected.update(set(set_fields.keys()) & PROTECTED_FIELDS)
        update_set["dashboard_edited_fields"] = sorted(new_protected)
        await db.academy_members.update_one(
            {"_id": existing["_id"]}, {"$set": update_set}
        )
        logger.info(
            f"[students-db] zapier intake updated email={email_l} "
            f"id={existing['_id']} fields={list(set_fields.keys())}"
        )
        return {
            "ok": True,
            "id": existing["_id"],
            "action": "updated",
            "fields": sorted(set_fields.keys()),
        }

    # Insert — new row with dashboard-generated id
    new_id = f"auto:{uuid.uuid4()}"
    insert_doc: dict[str, Any] = dict(set_fields)
    insert_doc["_id"] = new_id
    insert_doc["synced_from_monday"] = False
    insert_doc["created_at"] = now
    insert_doc["dashboard_edited_at"] = now
    insert_doc["dashboard_edited_by"] = "zapier-intake"
    insert_doc["intake_seen_at"] = now
    insert_doc["dashboard_edited_fields"] = sorted(
        set(set_fields.keys()) & PROTECTED_FIELDS
    )
    await db.academy_members.insert_one(insert_doc)
    logger.info(
        f"[students-db] zapier intake created email={email_l} "
        f"id={new_id} fields={list(set_fields.keys())}"
    )

    # Outbound webhook fan-out for the new row's initial columns (treats
    # the insert as a transition from "didn't exist" to "exists with these
    # values", so subscribed downstream zaps fire on cohort assignment etc).
    diff = {k: v for k, v in set_fields.items() if k in PROTECTED_FIELDS}
    if diff:
        asyncio.create_task(
            webhooks_outbound.notify_column_changes(
                db, item_id=new_id, fields_changed=diff, student=insert_doc,
            )
        )

    return {
        "ok": True,
        "id": new_id,
        "action": "created",
        "fields": sorted(set_fields.keys()),
    }


# ----------------------------------------------- Webhook subscription admin
# Manage the subscribers that listen for column-change events. Authenticated
# (dashboard user only) — these are equivalent to changing a Monday zap
# trigger.
#
# NOTE: these live under /api/webhook-subscriptions, NOT /api/students-db/...,
# deliberately. A single-segment path like /students-db/webhook-subscriptions
# is shadowed by the GET /students-db/{monday_item_id} route declared above
# (Starlette matches in declaration order), so it would 404 as "student not
# found". A separate prefix sidesteps that.

class WebhookSubscriptionCreate(BaseModel):
    name: str
    column: str
    url: str
    active: bool = True

    class Config:
        extra = "forbid"


def _serialise_subscription(doc: dict) -> dict:
    """Drop Mongo's _id and render datetimes as ISO strings for the UI."""
    out = {k: v for k, v in doc.items() if k != "_id"}
    ca = out.get("created_at")
    if isinstance(ca, datetime):
        out["created_at"] = ca.isoformat()
    return out


@router.get("/webhook-subscriptions/columns")
async def list_webhook_columns(
    user: dict = Depends(require_admin),
):
    """The columns a subscription may listen on — the automation-writable
    field allowlist (PROTECTED_FIELDS). Populates the create-form dropdown."""
    return {"columns": sorted(PROTECTED_FIELDS)}


@router.get("/webhook-subscriptions")
async def list_webhook_subscriptions(
    user: dict = Depends(require_admin),
):
    cursor = db.dashboard_webhook_subscriptions.find({})
    items = [_serialise_subscription(s) async for s in cursor]
    items.sort(key=lambda s: (s.get("column", ""), s.get("name", "")))
    return {"items": items, "count": len(items)}


@router.post("/webhook-subscriptions")
async def create_webhook_subscription(
    payload: WebhookSubscriptionCreate,
    user: dict = Depends(require_admin),
):
    if payload.column not in PROTECTED_FIELDS:
        raise HTTPException(
            400,
            f"column must be one of: {sorted(PROTECTED_FIELDS)}",
        )
    if not payload.url.startswith("https://"):
        raise HTTPException(400, "url must be https://")
    doc = {
        "id": str(uuid.uuid4()),
        "name": payload.name.strip(),
        "column": payload.column,
        "url": payload.url.strip(),
        "active": payload.active,
        "created_at": datetime.now(timezone.utc),
        "created_by": user.get("email") or user.get("id"),
    }
    await db.dashboard_webhook_subscriptions.insert_one(doc)
    return _serialise_subscription(doc)


@router.delete("/webhook-subscriptions/{sub_id}")
async def delete_webhook_subscription(
    sub_id: str,
    user: dict = Depends(require_admin),
):
    res = await db.dashboard_webhook_subscriptions.delete_one({"id": sub_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Subscription not found")
    return {"ok": True}
