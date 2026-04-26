"""
Students-at-risk: high-spend Stripe customers who are dormant on Circle.

A student is "at risk" if their lifetime Stripe spend (last 365 days, GBP,
succeeded charges, net of refunds) is >= MIN_SPEND_GBP and *either* they have
never logged into Circle (no `last_seen_at`) *or* their last Circle activity
was more than DORMANT_DAYS days ago.

Result is cached in Mongo `at_risk_cache` for 1 hour because the underlying
Stripe scan can pull a few thousand charges.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone, timedelta

import httpx

from connectors import STRIPE_API, TIMEOUT, _stripe_auth, _stripe_list_all

MIN_SPEND_GBP = 1000.0
DORMANT_DAYS = 30
LOOKBACK_DAYS = 365
CACHE_TTL_HOURS = 24


def _to_unix(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


async def _aggregate_stripe_spend_by_customer(lookback_days: int) -> dict[str, dict]:
    """
    Pull all succeeded GBP charges in the last `lookback_days` days and aggregate
    them by Stripe customer ID. Returns {cust_id: {email, name, total_pence,
    last_charge_ts, charge_count}}.
    """
    end_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = end_ts - lookback_days * 86400

    by_cust: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        charges = await _stripe_list_all(
            c, "/charges", {"created[gte]": start_ts, "created[lte]": end_ts}
        )
        for ch in charges:
            if ch.get("currency") != "gbp":
                continue
            if ch.get("status") != "succeeded" or not ch.get("paid"):
                continue
            cust_id = ch.get("customer")
            if not cust_id:
                continue
            net = int(ch.get("amount", 0)) - int(ch.get("amount_refunded", 0))
            if net <= 0:
                continue

            entry = by_cust.setdefault(
                cust_id,
                {
                    "id": cust_id,
                    "email": (ch.get("billing_details") or {}).get("email")
                    or ch.get("receipt_email"),
                    "name": (ch.get("billing_details") or {}).get("name"),
                    "total_pence": 0,
                    "charge_count": 0,
                    "last_charge_ts": None,
                },
            )
            entry["total_pence"] += net
            entry["charge_count"] += 1
            t = ch.get("created")
            if t and (entry["last_charge_ts"] is None or t > entry["last_charge_ts"]):
                entry["last_charge_ts"] = t
            # Prefer non-empty email/name if a later charge has it
            if not entry["email"]:
                entry["email"] = (ch.get("billing_details") or {}).get("email") or ch.get(
                    "receipt_email"
                )
            if not entry["name"]:
                entry["name"] = (ch.get("billing_details") or {}).get("name")
    return by_cust


async def compute_at_risk(db) -> dict:
    """Return the at-risk list. Skips Stripe customers below MIN_SPEND_GBP."""
    spend_map = await _aggregate_stripe_spend_by_customer(LOOKBACK_DAYS)

    # Pull Circle members cache for lookup by email
    circle_doc = await db.circle_members_cache.find_one({"_id": "all"}, {"_id": 0})
    circle_by_email: dict[str, dict] = {}
    if circle_doc:
        for m in circle_doc.get("members") or []:
            email = (m.get("email") or "").lower().strip()
            if email:
                circle_by_email[email] = m

    now = datetime.now(timezone.utc)
    dormant_cutoff = now - timedelta(days=DORMANT_DAYS)

    high_spenders: list[dict] = []
    for cust in spend_map.values():
        total_gbp = cust["total_pence"] / 100.0
        if total_gbp < MIN_SPEND_GBP:
            continue
        email = (cust.get("email") or "").lower().strip()
        circle = circle_by_email.get(email) if email else None

        last_seen_iso = circle.get("last_seen_at") if circle else None
        last_seen_dt = None
        days_dormant = None
        if last_seen_iso:
            try:
                last_seen_dt = datetime.fromisoformat(
                    last_seen_iso.replace("Z", "+00:00")
                )
                days_dormant = (now - last_seen_dt).days
            except (ValueError, TypeError):
                last_seen_dt = None

        if circle is None:
            risk_status = "no_circle_account"
        elif last_seen_dt is None:
            risk_status = "never_logged_in"
        elif last_seen_dt < dormant_cutoff:
            risk_status = "dormant"
        else:
            # Active on Circle — not at risk
            continue

        high_spenders.append(
            {
                "stripe_customer_id": cust["id"],
                "email": email or None,
                "name": cust.get("name") or (circle.get("name") if circle else None),
                "lifetime_gbp": round(total_gbp, 2),
                "charge_count": cust["charge_count"],
                "last_charge_at": (
                    datetime.fromtimestamp(cust["last_charge_ts"], tz=timezone.utc).isoformat()
                    if cust["last_charge_ts"]
                    else None
                ),
                "circle_avatar_url": circle.get("avatar_url") if circle else None,
                "circle_last_seen_at": last_seen_iso,
                "days_dormant": days_dormant,
                "risk_status": risk_status,
            }
        )

    high_spenders.sort(key=lambda x: -x["lifetime_gbp"])

    counts = {
        "dormant": sum(1 for s in high_spenders if s["risk_status"] == "dormant"),
        "never_logged_in": sum(1 for s in high_spenders if s["risk_status"] == "never_logged_in"),
        "no_circle_account": sum(1 for s in high_spenders if s["risk_status"] == "no_circle_account"),
    }

    return {
        "min_spend_gbp": MIN_SPEND_GBP,
        "dormant_days": DORMANT_DAYS,
        "lookback_days": LOOKBACK_DAYS,
        "computed_at": now.isoformat(),
        "total_at_risk": len(high_spenders),
        "counts": counts,
        "students": high_spenders,
    }


async def get_at_risk_cached(db, force: bool = False) -> dict:
    """Cached wrapper. Cache key is fixed because the result is global.
    Returns cached payload if available and fresh; otherwise returns a
    `computing=True` placeholder and lets the background warmer fill the cache.
    """
    cache_key = "at_risk:v1"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS)

    cached = await db.at_risk_cache.find_one({"_id": cache_key}, {"_id": 0})
    fresh = False
    if cached and cached.get("cached_at"):
        cached_at = cached["cached_at"]
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        fresh = cached_at > cutoff

    if cached and fresh and not force:
        return {**cached["payload"], "cached": True}

    # If we have stale cache and not forcing, return it but flag stale
    if cached and not force:
        return {**cached["payload"], "cached": True, "stale": True}

    # No cache yet — return placeholder
    return {
        "computing": True,
        "min_spend_gbp": MIN_SPEND_GBP,
        "dormant_days": DORMANT_DAYS,
        "lookback_days": LOOKBACK_DAYS,
        "total_at_risk": 0,
        "counts": {"dormant": 0, "never_logged_in": 0, "no_circle_account": 0},
        "students": [],
        "message": "First-time scan in progress. Refresh in a few minutes.",
    }


async def warm_at_risk_cache(db, force: bool = False) -> dict:
    """Compute at-risk list and store it in the cache. Safe to call from
    background tasks / schedulers. Skips if cache is fresh and `force=False`.
    """
    cache_key = "at_risk:v1"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS)
    cached = await db.at_risk_cache.find_one({"_id": cache_key}, {"_id": 0})
    if not force and cached and cached.get("cached_at"):
        cached_at = cached["cached_at"]
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        if cached_at > cutoff:
            return cached["payload"]

    payload = await compute_at_risk(db)
    await db.at_risk_cache.update_one(
        {"_id": cache_key},
        {"$set": {"payload": payload, "cached_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return payload
