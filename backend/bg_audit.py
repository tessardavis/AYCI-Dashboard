"""
Boost & Go reconciliation audit.

Finds students who BOUGHT Boost & Go (per Stripe) but aren't flagged as B&G in
the dashboard. The dashboard's `boost_and_go` is only a mirror of Monday's
"Boost + Go" column, so a missed Kajabi→Monday update leaves a real buyer
unflagged - and the dashboard can't self-detect that. Stripe is the purchase
source of truth, so we cross-reference against it.

Read-only (surfaces the gap; no writes). The heavy Stripe scan runs in the
background and the result is cached in db.cache (_id "bg_audit"), so the admin
GET returns instantly instead of blocking on the Vercel proxy timeout.

Matching is by keyword (default "boost") in each succeeded charge's
description / statement descriptor / metadata - Kajabi typically puts the offer
name there. The result echoes the distinct matched descriptions + a sample of
Stripe products so we can CONFIRM the keyword is hitting real B&G charges before
trusting (or acting on) the buyer list.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

# Match the Boost & Go family ("Boost & Go", "Boost&GO", "Boost and Go",
# "Boost & Go Plus") but NOT "Booster" products (Turbo Booster / Prep Booster) -
# "boost" alone false-matches "boostER", so we require the "go".
_BG_RE = re.compile(r"boost\s*&?\s*(?:and\s*)?go", re.I)

import httpx

from db import db
from connectors import STRIPE_API, _stripe_auth, _stripe_list_all, TIMEOUT

logger = logging.getLogger(__name__)

CACHE_ID = "bg_audit"
DEFAULT_KEYWORD = "boost"


def _email_from_charge(charge: Any) -> Optional[str]:
    if not isinstance(charge, dict):
        return None
    cust = charge.get("customer")
    cust_email = cust.get("email") if isinstance(cust, dict) else None
    return (
        charge.get("receipt_email")
        or (charge.get("billing_details") or {}).get("email")
        or cust_email
    )


def _name_from_charge(charge: Any) -> Optional[str]:
    if not isinstance(charge, dict):
        return None
    cust = charge.get("customer")
    cust_name = cust.get("name") if isinstance(cust, dict) else None
    return ((charge.get("billing_details") or {}).get("name") or cust_name) or None


def _charge_haystack(ch: dict) -> str:
    parts = [
        ch.get("description") or "",
        ch.get("statement_descriptor") or "",
        ch.get("calculated_statement_descriptor") or "",
    ]
    parts += [str(v) for v in (ch.get("metadata") or {}).values()]
    return " ".join(parts).lower()


def _already_marked_bg(row: dict) -> bool:
    b = (row.get("boost_and_go") or "").strip().lower()
    return ("b&g" in b) or ("boost" in b) or (b == "upgraded")


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


async def _stripe_boost_products(c: httpx.AsyncClient, keyword: str) -> list:
    """Stripe products whose name contains the keyword - for transparency, so we
    can see what 'Boost' products exist (helps confirm the naming)."""
    try:
        products = await _stripe_list_all(c, "/products", {"active": "true"})
    except Exception as e:
        logger.info(f"[bg-audit] product list skipped: {e}")
        return []
    return [
        {"id": p.get("id"), "name": p.get("name")}
        for p in products
        if keyword in (p.get("name") or "").lower()
    ]


def _bg_level_from_bought(bought: list) -> str:
    """'B&G Plus' if any purchase mentions Plus, else 'B&G' - matching the label
    convention the dashboard's B&G logic recognises ('b&g' substring + 'plus')."""
    return "B&G Plus" if "plus" in " ".join(bought or []).lower() else "B&G"


async def apply_backfill(dry_run: bool = True) -> dict:
    """Set `boost_and_go` on the audit's `unflagged` buyers (B&G / B&G Plus from
    what they bought), pinned in dashboard_edited_fields so the Monday sync won't
    revert it to "Offer Due". Acts on the most recent cached audit. dry_run=True
    just previews. Fixes the dashboard only - the upstream Monday column / Kajabi
    zap still needs sorting separately, but the pin keeps the dashboard correct."""
    cached = await get_cached()
    if not cached or not cached.get("ok"):
        return {"ok": False, "error": "Run the audit first (no cached result)."}
    unflagged = cached.get("unflagged") or []
    now = datetime.now(timezone.utc)
    planned, applied = [], 0
    for u in unflagged:
        level = _bg_level_from_bought(u.get("bought"))
        entry = {"id": u["id"], "name": u.get("name"), "email": u.get("email"),
                 "from": u.get("current_boost_and_go"), "to": level, "bought": u.get("bought")}
        if not dry_run:
            row = await db.academy_members.find_one(
                {"_id": u["id"]}, {"dashboard_edited_fields": 1})
            if not row:
                entry["skipped"] = "row not found"
                planned.append(entry)
                continue
            pinned = sorted(set(row.get("dashboard_edited_fields") or []) | {"boost_and_go"})
            await db.academy_members.update_one(
                {"_id": u["id"]},
                {"$set": {
                    "boost_and_go": level,
                    "dashboard_edited_fields": pinned,
                    "dashboard_edited_at": now,
                    "dashboard_edited_by": "bg-audit-backfill",
                }},
            )
            applied += 1
        planned.append(entry)
    return {
        "ok": True,
        "dry_run": dry_run,
        "based_on_audit_as_of": cached.get("as_of"),
        "count": len(planned),
        "applied": applied,
        "students": planned,
        "note": "buyer_not_in_dashboard cases can't be backfilled (no row) - investigate separately.",
    }


async def run_audit(keyword: str = DEFAULT_KEYWORD) -> dict:
    """Scan Stripe charges for B&G purchases and flag buyers not marked B&G in
    the dashboard. Stores the result for the admin GET to read."""
    keyword = (keyword or DEFAULT_KEYWORD).strip().lower()
    if not (os.environ.get("STRIPE_API_KEY") or "").strip():
        result = {"ok": False, "error": "STRIPE_API_KEY not configured"}
        await _store(result)
        return result

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            products = await _stripe_boost_products(c, keyword)
            charges = await _stripe_list_all(c, "/charges", {"expand[]": ["data.customer"]})
    except Exception as e:
        logger.exception("[bg-audit] stripe scan failed")
        result = {"ok": False, "error": f"Stripe scan failed: {str(e)[:200]}"}
        await _store(result)
        return result

    buyers: dict[str, dict] = {}          # email -> {examples:set, charges:int}
    matched_descriptions: dict[str, int] = {}
    refunded_excluded = 0
    for ch in charges:
        if ch.get("status") != "succeeded" or not ch.get("paid"):
            continue
        if not _BG_RE.search(_charge_haystack(ch)):
            continue  # require "boost & go" - excludes Turbo/Prep "Booster"
        if ch.get("refunded"):
            refunded_excluded += 1
            continue  # fully-refunded B&G purchase - don't flag them as B&G
        desc = (ch.get("description") or "").strip()
        matched_descriptions[desc] = matched_descriptions.get(desc, 0) + 1
        email = (_email_from_charge(ch) or "").strip().lower()
        if not email:
            continue
        b = buyers.setdefault(email, {"examples": set(), "charges": 0, "name": None})
        b["charges"] += 1
        if desc:
            b["examples"].add(desc)
        if not b.get("name"):
            b["name"] = _name_from_charge(ch)

    unflagged, already_flagged, not_in_db = [], 0, []
    for email, info in buyers.items():
        examples = sorted(info["examples"])[:3]
        row = await db.academy_members.find_one(
            {"$or": [{"email": email}, {"circle_email": email}]},
            {"_id": 1, "name": 1, "email": 1, "tier": 1, "boost_and_go": 1},
        )
        if not row:
            not_in_db.append({"email": email, "name": info.get("name"), "bought": examples})
        elif _already_marked_bg(row):
            already_flagged += 1
        else:
            unflagged.append({
                "id": row["_id"],
                "name": row.get("name"),
                "email": row.get("email") or email,
                "tier": row.get("tier"),
                "current_boost_and_go": row.get("boost_and_go") or None,
                "bought": examples,
            })

    unflagged.sort(key=lambda x: x.get("name") or "")
    result = {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "match_rule": "regex 'boost & go' (excludes Turbo/Prep Booster)",
        "charges_scanned": len(charges),
        # Transparency: confirm the keyword is hitting real B&G charges.
        "stripe_boost_products": products,
        "matched_charge_descriptions": dict(
            sorted(matched_descriptions.items(), key=lambda kv: -kv[1])[:25]
        ),
        "counts": {
            "bg_buyers": len(buyers),
            "already_flagged": already_flagged,
            "unflagged": len(unflagged),
            "buyer_not_in_dashboard": len(not_in_db),
            "refunded_excluded": refunded_excluded,
        },
        "unflagged": unflagged,
        "buyer_not_in_dashboard": not_in_db[:100],
    }
    await _store(result)
    logger.info(
        f"[bg-audit] scanned {len(charges)} charges · {len(buyers)} B&G buyers · "
        f"{len(unflagged)} unflagged"
    )
    return result
