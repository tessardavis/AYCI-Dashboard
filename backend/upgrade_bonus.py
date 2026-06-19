"""
Retrospective upgrade-bonus detection.

During a launch, a student who BUYS an upgrade offer on Kajabi earns a bonus
30-min 1:1 call (on top of any signup bonus). There's no Kajabi API — Kajabi
charges through Stripe — so Stripe is the purchase source of truth, exactly
like the Boost & Go audit (see bg_audit.py).

This module scans Stripe charges inside a launch window, matches the upgrade
offer by keyword (description / statement descriptor / metadata — Kajabi puts
the offer name there), and records ONE grant per qualifying charge in
`upgrade_bonus_grants` (keyed by the Stripe charge id, so re-running never
double-grants). The over-allowance check (over_allowance_alerts.py) counts a
student's grants and folds them into their bonus allowance — so a legitimate
upgrade purchase stops the student being false-flagged as over-allowance.

Deliberately Stripe + dashboard only — no Monday column (we're retiring that
board). Match is keyword-based and the report echoes the distinct matched
descriptions + Stripe products, so we can CONFIRM the keyword is hitting the
real upgrade offer before applying (dry-run by default).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, date
from typing import Any, Optional

import httpx

from db import db
from connectors import _stripe_list_all, TIMEOUT
# Reuse the charge helpers the B&G audit already proved out.
from bg_audit import _email_from_charge, _name_from_charge, _charge_haystack

logger = logging.getLogger(__name__)

CACHE_ID = "upgrade_bonus_audit"
GRANTS = "upgrade_bonus_grants"

# Default launch window for the Jun-26 cohort (Arub's bonus windows span
# 31 May → 22 Jun 2026; a small buffer either side is harmless because the
# keyword still has to match the upgrade offer). Overridable per call.
DEFAULT_WINDOW_START = "2026-05-28"
DEFAULT_WINDOW_END = "2026-06-23"
DEFAULT_KEYWORD = "upgrade"
DEFAULT_COHORT = "June 26"


def _parse_day(s: str, *, end: bool) -> Optional[datetime]:
    """Parse a yyyy-mm-dd into a UTC datetime at the start (or end) of day."""
    try:
        d = date.fromisoformat((s or "").strip())
    except ValueError:
        return None
    if end:
        return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)


def _charge_dt(ch: dict) -> Optional[datetime]:
    created = ch.get("created")
    if not isinstance(created, (int, float)):
        return None
    return datetime.fromtimestamp(int(created), tz=timezone.utc)


async def _store(result: dict) -> None:
    await db.cache.update_one(
        {"_id": CACHE_ID},
        {"$set": {"payload": result, "cached_at": datetime.now(timezone.utc)}},
        upsert=True,
    )


async def get_cached() -> Optional[dict]:
    doc = await db.cache.find_one({"_id": CACHE_ID}, {"_id": 0})
    if not doc:
        return None
    payload = doc.get("payload") or {}
    ca = doc.get("cached_at")
    payload["cached_at"] = ca.isoformat() if hasattr(ca, "isoformat") else ca
    return payload


async def _stripe_products(c: httpx.AsyncClient, keyword: str) -> list:
    """Active Stripe products whose name contains the keyword — transparency,
    so we can eyeball which 'upgrade' products exist."""
    try:
        products = await _stripe_list_all(c, "/products", {"active": "true"})
    except Exception as e:
        logger.info(f"[upgrade-bonus] product list skipped: {e}")
        return []
    return [
        {"id": p.get("id"), "name": p.get("name")}
        for p in products
        if keyword in (p.get("name") or "").lower()
    ]


async def _match_student(email: str) -> Optional[dict]:
    """Resolve a buyer email to a student row across the full email set
    (combined-identity: email / circle_email / other_emails)."""
    email = (email or "").strip().lower()
    if not email:
        return None
    rx = re.escape(email)
    return await db.academy_members.find_one(
        {"$or": [
            {"email": email},
            {"circle_email": email},
            {"other_emails": {"$regex": rx, "$options": "i"}},
        ]},
        {"_id": 1, "name": 1, "email": 1, "tier": 1},
    )


async def run_audit(
    *,
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
    keyword: str = DEFAULT_KEYWORD,
    cohort: str = DEFAULT_COHORT,
) -> dict:
    """Scan Stripe for upgrade-offer purchases inside the launch window and
    build the proposed grant list. Read-only — stores the result for the GET
    to read; `apply_grants` does the writing."""
    keyword = (keyword or DEFAULT_KEYWORD).strip().lower()
    start = _parse_day(window_start, end=False)
    end = _parse_day(window_end, end=True)
    if not start or not end:
        result = {"ok": False, "error": "window_start / window_end must be yyyy-mm-dd"}
        await _store(result)
        return result

    import os
    if not (os.environ.get("STRIPE_API_KEY") or "").strip():
        result = {"ok": False, "error": "STRIPE_API_KEY not configured"}
        await _store(result)
        return result

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            products = await _stripe_products(c, keyword)
            charges = await _stripe_list_all(
                c, "/charges",
                {"expand[]": ["data.customer"],
                 "created[gte]": str(int(start.timestamp())),
                 "created[lte]": str(int(end.timestamp()))},
            )
    except Exception as e:
        logger.exception("[upgrade-bonus] stripe scan failed")
        result = {"ok": False, "error": f"Stripe scan failed: {str(e)[:200]}"}
        await _store(result)
        return result

    matched_descriptions: dict[str, int] = {}
    refunded_excluded = 0
    grants: list[dict] = []          # one per qualifying charge
    not_in_db: list[dict] = []
    seen_no_db: set[str] = set()

    for ch in charges:
        if ch.get("status") != "succeeded" or not ch.get("paid"):
            continue
        if keyword not in _charge_haystack(ch):
            continue
        dt = _charge_dt(ch)
        if not dt or dt < start or dt > end:
            continue  # outside the launch window (defensive — Stripe already filtered)
        if ch.get("refunded"):
            refunded_excluded += 1
            continue
        desc = (ch.get("description") or "").strip()
        matched_descriptions[desc] = matched_descriptions.get(desc, 0) + 1
        email = (_email_from_charge(ch) or "").strip().lower()
        if not email:
            continue
        row = await _match_student(email)
        if not row:
            if email not in seen_no_db:
                seen_no_db.add(email)
                not_in_db.append({"email": email, "name": _name_from_charge(ch), "bought": desc})
            continue
        grants.append({
            "charge_id": ch.get("id"),
            "email": email,
            "student_id": row["_id"],
            "student_name": row.get("name"),
            "tier": row.get("tier"),
            "charged_at": dt.isoformat(),
            "amount": (ch.get("amount") or 0) / 100.0,
            "currency": (ch.get("currency") or "").upper(),
            "description": desc,
            "cohort": cohort,
        })

    grants.sort(key=lambda g: (g.get("student_name") or "", g.get("charged_at") or ""))
    # Per-student tally (a student can have >1 qualifying charge → >1 bonus)
    per_student: dict[str, int] = {}
    for g in grants:
        per_student[str(g["student_id"])] = per_student.get(str(g["student_id"]), 0) + 1

    result = {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "window": {"start": window_start, "end": window_end},
        "keyword": keyword,
        "cohort": cohort,
        "charges_scanned": len(charges),
        "match_rule": f"keyword '{keyword}' in charge description / statement descriptor / metadata, within the window",
        "stripe_upgrade_products": products,
        "matched_charge_descriptions": dict(
            sorted(matched_descriptions.items(), key=lambda kv: -kv[1])[:25]
        ),
        "counts": {
            "qualifying_charges": len(grants),
            "students_matched": len(per_student),
            "buyer_not_in_dashboard": len(not_in_db),
            "refunded_excluded": refunded_excluded,
        },
        "grants": grants,
        "buyer_not_in_dashboard": not_in_db[:100],
    }
    await _store(result)
    logger.info(
        f"[upgrade-bonus] scanned {len(charges)} charges in {window_start}..{window_end} · "
        f"{len(grants)} qualifying · {len(per_student)} students · {len(not_in_db)} buyers not in DB"
    )
    return result


async def apply_grants(dry_run: bool = True) -> dict:
    """Persist the latest audit's grants into `upgrade_bonus_grants` (upsert by
    Stripe charge id, so it's idempotent). Also REMOVES any prior grant for the
    same cohort whose charge no longer qualifies (e.g. later refunded), so the
    tally stays correct. The over-allowance check reads these grants and adds
    them to each student's bonus allowance. dry_run=True just previews."""
    cached = await get_cached()
    if not cached or not cached.get("ok"):
        return {"ok": False, "error": "Run the audit first (no cached result)."}
    cohort = cached.get("cohort") or DEFAULT_COHORT
    grants = cached.get("grants") or []
    keep_ids = {g["charge_id"] for g in grants if g.get("charge_id")}

    # Stale grants for this cohort that are no longer in the qualifying set.
    stale = []
    async for d in db[GRANTS].find({"cohort": cohort}, {"_id": 1}):
        if d["_id"] not in keep_ids:
            stale.append(d["_id"])

    now = datetime.now(timezone.utc)
    if not dry_run:
        for g in grants:
            cid = g.get("charge_id")
            if not cid:
                continue
            await db[GRANTS].update_one(
                {"_id": cid},
                {"$set": {**g, "_id": cid, "detected_at": now}},
                upsert=True,
            )
        if stale:
            await db[GRANTS].delete_many({"_id": {"$in": stale}})

    return {
        "ok": True,
        "dry_run": dry_run,
        "based_on_audit_as_of": cached.get("as_of"),
        "cohort": cohort,
        "would_grant": len(grants),
        "would_remove_stale": len(stale),
        "applied": 0 if dry_run else len(grants),
        "removed": 0 if dry_run else len(stale),
        "grants": grants,
        "note": "buyer_not_in_dashboard cases can't be granted (no student row) — add their alt email to the matching record, then re-run.",
    }


async def grant_counts_by_student() -> dict[str, int]:
    """student_id -> number of qualifying upgrade-bonus grants. Used by the
    over-allowance check to top up each student's bonus allowance."""
    out: dict[str, int] = {}
    async for g in db[GRANTS].find({"student_id": {"$ne": None}}, {"_id": 0, "student_id": 1}):
        sid = str(g.get("student_id") or "")
        if sid:
            out[sid] = out.get(sid, 0) + 1
    return out
