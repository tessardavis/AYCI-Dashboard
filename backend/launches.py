"""
Launch dashboard data loaders.

Pulls webinar registrations from ConvertKit (using the per-launch tag pattern
"[AYCI <CODE>] Webinar - Registered - <SOURCE>") and sales from Stripe (filtered
by launch date window), aggregated by day.

A `Launch.code` like "APR-26" maps to multiple Kit tags. We discover them once
per call by searching the tag list.
"""
from __future__ import annotations

import logging
import re
import asyncio
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from connectors import (
    CONVERTKIT_V3,
    STRIPE_API,
    TIMEOUT,
    _ck_secret,
    _stripe_auth,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- Caching
# Stale-while-revalidate wrappers around fetch_sales / fetch_registrations.
# - First call: compute + cache + return.
# - Subsequent fresh hit (< ttl_min): return cached payload (sub-50 ms).
# - Subsequent stale hit (>= ttl_min): return STALE cached payload immediately
#   AND fire off a background refresh so the next caller sees fresh data.
# This gives the team near-instant dashboard loads regardless of cache state,
# while ensuring data eventually catches up to reality.

_FN_CACHE = "fn_cache"
_BG_TASKS: dict[str, asyncio.Task] = {}


async def _stale_while_revalidate(
    db, key: str, ttl_min: int, compute_fn,
):
    cached = await db[_FN_CACHE].find_one({"_id": key}, {"_id": 0})
    now = datetime.now(timezone.utc)
    fresh_cutoff = now - timedelta(minutes=ttl_min)

    is_fresh = False
    if cached and cached.get("cached_at"):
        ca = cached["cached_at"]
        if ca.tzinfo is None:
            ca = ca.replace(tzinfo=timezone.utc)
        is_fresh = ca > fresh_cutoff

    async def _refresh():
        try:
            payload = await compute_fn()
            await db[_FN_CACHE].update_one(
                {"_id": key},
                {"$set": {"payload": payload, "cached_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
            return payload
        finally:
            _BG_TASKS.pop(key, None)

    if cached and is_fresh:
        return cached["payload"]

    if cached and not is_fresh:
        # Stale — return cached, kick off a background refresh (deduped by key)
        if key not in _BG_TASKS:
            _BG_TASKS[key] = asyncio.create_task(_refresh())
        return cached["payload"]

    # No cache — must compute synchronously
    return await _refresh()


async def cached_fetch_sales(db, start_iso: str, end_iso: str, *, ttl_min: int = 60) -> dict:
    """Stale-while-revalidate cache around fetch_sales(start, end)."""
    key = f"fn_sales:{start_iso}:{end_iso}"
    return await _stale_while_revalidate(
        db, key, ttl_min, lambda: fetch_sales(start_iso, end_iso)
    )


async def cached_fetch_registrations(db, code: str, start_iso: str, end_iso: str, *, ttl_min: int = 60) -> dict:
    """Stale-while-revalidate cache around fetch_registrations(code, start, end)."""
    key = f"fn_regs:{code}:{start_iso}:{end_iso}"
    return await _stale_while_revalidate(
        db, key, ttl_min, lambda: fetch_registrations(code, start_iso, end_iso)
    )


# -------------------------------------------------------- Webinar registrations
async def _list_kit_tags(c: httpx.AsyncClient) -> list[dict]:
    r = await c.get(f"{CONVERTKIT_V3}/tags", params={"api_secret": _ck_secret()})
    r.raise_for_status()
    return r.json().get("tags", [])


def _tag_source(tag_name: str, code: str) -> Optional[str]:
    """
    Given a tag name and a launch code, return the source label or None
    if the tag is not a webinar-registration tag for this launch.
    Example: "[AYCI APR-26] Webinar - Registered - Homepage" → "Homepage"
    """
    pattern = rf"^\[AYCI {re.escape(code)}\] Webinar - Registered - (.+)$"
    m = re.match(pattern, tag_name, re.IGNORECASE)
    if not m:
        return None
    src = m.group(1).strip()
    # Skip aggregate "All" tag - we'll synthesise All from sums
    if src.lower() in ("all", "no sale"):
        return None
    return src


async def _ck_tag_subscribers(c: httpx.AsyncClient, tag_id: int) -> list[dict]:
    """Return all subscribers for a Kit tag with created_at + email + name."""
    out: list[dict] = []
    page = 1
    while page <= 200:
        r = await c.get(
            f"{CONVERTKIT_V3}/tags/{tag_id}/subscriptions",
            params={"api_secret": _ck_secret(), "page": page, "sort_order": "desc"},
        )
        r.raise_for_status()
        body = r.json()
        subs = body.get("subscriptions", [])
        if not subs:
            break
        for s in subs:
            sub = s.get("subscriber") or {}
            ca = s.get("created_at") or sub.get("created_at")
            if ca:
                out.append({
                    "email": (sub.get("email_address") or "").lower(),
                    "first_name": sub.get("first_name"),
                    "created_at": ca,
                })
        if page >= body.get("total_pages", 1):
            break
        page += 1
    return out


async def fetch_registrations(code: str, start_iso: str, end_iso: str) -> dict:
    """
    Returns:
      {
        "total": N,
        "by_source": [{"source": "Homepage", "count": 320}, ...],
        "by_day": [{"date": "2026-04-01", "total": 12, "by_source": {...}}, ...],
      }
    """
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))

    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        tags = await _list_kit_tags(c)
        relevant: list[tuple[int, str]] = []
        for t in tags:
            src = _tag_source(t.get("name", ""), code)
            if src:
                relevant.append((t["id"], src))

        # Fetch subscribers per tag in parallel
        import asyncio
        tag_results = await asyncio.gather(
            *[_ck_tag_subscribers(c, tid) for tid, _ in relevant],
            return_exceptions=True,
        )

    by_source_count: dict[str, int] = defaultdict(int)
    by_day: dict[str, dict] = {}

    seen_emails: set[str] = set()  # for dedup global total

    for (tid, src), subs in zip(relevant, tag_results):
        if isinstance(subs, Exception):
            logger.warning(f"Kit tag {tid} ({src}) failed: {subs}")
            continue
        for sub in subs:
            try:
                ca = datetime.fromisoformat(sub["created_at"].replace("Z", "+00:00"))
            except (ValueError, KeyError):
                continue
            if ca < start or ca > end:
                continue
            day = ca.date().isoformat()
            by_source_count[src] += 1
            day_bucket = by_day.setdefault(day, {"total": 0, "by_source": defaultdict(int)})
            day_bucket["total"] += 1
            day_bucket["by_source"][src] += 1
            seen_emails.add(sub["email"])

    by_source = sorted(
        [{"source": s, "count": n} for s, n in by_source_count.items()],
        key=lambda x: -x["count"],
    )
    by_day_list = sorted(
        [
            {"date": d, "total": v["total"], "by_source": dict(v["by_source"])}
            for d, v in by_day.items()
        ],
        key=lambda x: x["date"],
    )

    return {
        "total": sum(by_source_count.values()),
        "unique": len(seen_emails),
        "by_source": by_source,
        "by_day": by_day_list,
    }


# ---------------------------------------------------------------------- Sales
async def fetch_sales(start_iso: str, end_iso: str) -> dict:
    """
    Pull successful Stripe charges within the launch window and classify each
    one as a SIGNUP (first-ever paid charge by that customer) or UPGRADE
    (existing customer paying ≥ STRIPE_UPGRADE_MIN_GBP, or charge description
    mentions 'upgrade'). Anything else (small recurring renewals on existing
    customers) is excluded so the dashboard reflects launch sales only.

    Returns daily totals + breakdown by tier:
      Academy / Private Plus / VIP / Boost & Go / Private Plus upgrade /
      VIP upgrade / Other signup / Other upgrade.
    """
    import os as _os
    upgrade_min_pence = int(float(_os.environ.get("STRIPE_UPGRADE_MIN_GBP", "90")) * 100)

    start_ts = int(datetime.fromisoformat(start_iso.replace("Z", "+00:00")).timestamp())
    end_ts = int(datetime.fromisoformat(end_iso.replace("Z", "+00:00")).timestamp())

    # 1. Pull all succeeded GBP charges in window
    raw_charges: list[dict] = []
    last_starting_after: Optional[str] = None
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        while True:
            params = {
                "limit": 100,
                "created[gte]": start_ts,
                "created[lte]": end_ts,
            }
            if last_starting_after:
                params["starting_after"] = last_starting_after
            r = await c.get(f"{STRIPE_API}/charges", auth=_stripe_auth(), params=params)
            r.raise_for_status()
            body = r.json()
            for ch in body.get("data", []):
                if ch.get("status") != "succeeded" or ch.get("refunded"):
                    continue
                amount = int(ch.get("amount", 0)) - int(ch.get("amount_refunded", 0))
                if amount <= 0:
                    continue
                raw_charges.append(ch)
            if not body.get("has_more"):
                break
            last_starting_after = body["data"][-1]["id"] if body.get("data") else None
            if not last_starting_after:
                break

        # 2. Parallel-check prior-paid status per unique customer
        unique_customers = {ch["customer"] for ch in raw_charges if ch.get("customer")}
        async def _check(cust_id: str) -> tuple[str, bool]:
            try:
                from connectors import _customer_has_prior_paid
                return cust_id, await _customer_has_prior_paid(c, cust_id, start_ts)
            except Exception:
                return cust_id, False

        prior_results = await asyncio.gather(*[_check(cid) for cid in unique_customers])
        has_prior_map: dict[str, bool] = dict(prior_results)

    # 3. Classify each charge into a tier (or skip as renewal)
    # Boost & Go is excluded from launch metrics per team request.
    EXCLUDED_TIERS = {"Boost & Go"}

    by_day: dict[str, dict] = {}
    by_tier: dict[str, dict] = {}
    total_amount = 0
    total_count = 0
    # Per-customer dedup: each unique customer counted exactly once,
    # classified by whether they had prior paid charges before launch start.
    customers_new: set[str] = set()
    customers_legacy: set[str] = set()
    # Per-tier unique customer dedup — each customer counted once per tier
    # they bought into during the launch (so a customer who bought Academy
    # AND Private Plus upgrade contributes to both tiers, but only once each).
    tier_customers: dict[str, set[str]] = {}
    for ch in raw_charges:
        amount = int(ch.get("amount", 0)) - int(ch.get("amount_refunded", 0))
        cust = ch.get("customer")
        has_prior = has_prior_map.get(cust, False) if cust else False
        desc = (ch.get("description") or "").strip()
        tier = _classify_tier(desc, has_prior, amount, upgrade_min_pence)
        if tier is None:
            continue  # renewal — exclude
        if tier in EXCLUDED_TIERS:
            continue  # Boost & Go excluded from launch revenue/sales metrics
        day = datetime.fromtimestamp(ch.get("created", 0), tz=timezone.utc).date().isoformat()
        by_day.setdefault(day, {"amount": 0, "count": 0, "by_tier": defaultdict(int)})
        by_day[day]["amount"] += amount
        by_day[day]["count"] += 1
        by_day[day]["by_tier"][tier] += 1
        by_tier.setdefault(tier, {"amount": 0, "count_charges": 0})
        by_tier[tier]["amount"] += amount
        by_tier[tier]["count_charges"] += 1
        total_amount += amount
        total_count += 1
        if cust:
            tier_customers.setdefault(tier, set()).add(cust)
            if has_prior:
                customers_legacy.add(cust)
            else:
                customers_new.add(cust)

    by_day_list = sorted(
        [
            {
                "date": d,
                "amount_gbp": round(v["amount"] / 100.0, 2),
                "count": v["count"],
                "by_tier": {t: c for t, c in v["by_tier"].items()},
            }
            for d, v in by_day.items()
        ],
        key=lambda x: x["date"],
    )
    # Tier breakdown with unique-customer count + % of revenue
    total_revenue = sum(v["amount"] for v in by_tier.values()) or 1
    by_tier_list = sorted(
        [
            {
                "tier": t,
                "amount_gbp": round(v["amount"] / 100.0, 2),
                "count": len(tier_customers.get(t, set())),  # unique customers in this tier
                "charges": v["count_charges"],                # raw charge count for transparency
                "pct_of_revenue": round(v["amount"] * 100 / total_revenue, 1),
            }
            for t, v in by_tier.items()
        ],
        key=lambda x: -x["amount_gbp"],
    )

    # Unique-customer signup numbers (one person counted once)
    unique_new_signups = len(customers_new)
    unique_legacy_signups = len(customers_legacy)
    unique_total_signups = unique_new_signups + unique_legacy_signups

    aov_per_user = (
        round((total_amount / 100.0) / unique_total_signups, 2)
        if unique_total_signups else 0
    )

    return {
        "total_amount_gbp": round(total_amount / 100.0, 2),
        # Charge-based total kept for any historical caller (chart by_day uses it)
        "total_charge_count": total_count,
        # Unique-customer signup numbers (the team-facing source of truth)
        "total_count": unique_total_signups,
        "new_signup_count": unique_new_signups,
        "legacy_count": unique_legacy_signups,
        "unique_customers": unique_total_signups,
        "aov_per_user_gbp": aov_per_user,
        "by_tier": by_tier_list,
        "by_day": by_day_list,
        # Back-compat alias for any older callers
        "by_product": by_tier_list,
    }


def _classify_tier(
    description: str,
    has_prior: bool,
    amount_pence: int,
    upgrade_min_pence: int,
) -> Optional[str]:
    """
    Classify a Stripe charge into a launch tier. Returns None for renewal
    charges (existing customer + small amount + no 'upgrade' keyword) so they
    are excluded from launch sales counts/revenue.
    """
    d = (description or "").lower()
    is_upgrade_word = "upgrade" in d
    has_pp = "private plus" in d
    has_vip = "vip" in d
    has_boost = "boost" in d and "go" in d
    has_academy = (
        "academy" in d
        or "platinum" in d
        or "gold" in d
        or "silver" in d
    )

    if not has_prior:
        # First-time paying customer = signup, classified by tier mentioned
        if has_pp:
            return "Private Plus"
        if has_vip:
            return "VIP"
        if has_boost:
            return "Boost & Go"
        if has_academy:
            return "Academy"
        return "Other signup"

    # Existing customer
    if is_upgrade_word or amount_pence >= upgrade_min_pence:
        if has_pp:
            return "Private Plus upgrade"
        if has_vip:
            return "VIP upgrade"
        return "Other upgrade"

    # Small charge from existing customer = renewal/recurring → exclude
    return None


def _classify_product(description: str) -> str:
    """Legacy product classifier — kept for backward compatibility with older
    callers that still expect a product label.
    """
    d = (description or "").lower()
    if not d:
        return "Other"
    if "private plus" in d:
        return "Academy Private Plus"
    if "vip" in d:
        return "VIP"
    if "platinum" in d:
        return "Platinum"
    if "gold" in d:
        return "Gold"
    if "silver" in d:
        return "Silver"
    if "boost" in d and "go" in d:
        return "Boost & Go"
    if "academy" in d:
        return "Academy"
    if "upgrade" in d:
        return "Upgrade"
    return description[:60] or "Other"


# -------------------------------------------------------------- Pace tracker
async def compute_pace(db, current_launch: dict, previous_launches: list[dict]) -> dict:
    """
    Forecast a launch's final revenue based on the cumulative sales curve of
    previous launches at the same day_offset. Uses cached_fetch_sales so
    repeat calls within 60 min are sub-50 ms.
    """
    from datetime import datetime, timezone
    import asyncio

    if not current_launch.get("start_date"):
        return {"error": "Launch has no start_date"}

    start = datetime.fromisoformat(current_launch["start_date"]).date()
    today = datetime.now(timezone.utc).date()
    today_offset = (today - start).days
    if today_offset < 0:
        return {
            "today_offset": today_offset,
            "forecast": None,
            "explanation": "Launch hasn't started yet.",
            "confidence": "low",
        }

    end_date = datetime.fromisoformat(current_launch["end_date"]).date() if current_launch.get("end_date") else None
    days_to_close = (end_date - today).days if end_date else None

    # Fetch current launch sales + each previous launch in parallel
    end_iso = today.isoformat() + "T23:59:59Z"
    start_iso = current_launch["start_date"] + "T00:00:00Z"

    async def _fetch_prev(prev: dict) -> tuple[dict, dict] | None:
        if not prev.get("start_date") or not prev.get("end_date"):
            return None
        try:
            res = await cached_fetch_sales(
                db,
                prev["start_date"] + "T00:00:00Z",
                prev["end_date"] + "T23:59:59Z",
            )
        except Exception:
            return None
        return prev, res

    results = await asyncio.gather(
        cached_fetch_sales(db, start_iso, end_iso),
        *[_fetch_prev(p) for p in previous_launches],
        return_exceptions=False,
    )
    current_sales = results[0]
    prev_results = [r for r in results[1:] if r]
    today_amount = current_sales.get("total_amount_gbp", 0.0)

    ratios: list[dict] = []
    # Cumulative series for sparkline overlay
    current_cumul: list[dict] = []
    cum = 0.0
    current_start = datetime.fromisoformat(current_launch["start_date"]).date()
    for row in current_sales.get("by_day", []):
        try:
            d = datetime.fromisoformat(row["date"]).date()
        except ValueError:
            continue
        cum += row["amount_gbp"]
        current_cumul.append({"day_offset": (d - current_start).days, "value": round(cum, 2)})

    prev_cumul: list[dict] = []  # one entry per prior launch
    for prev, prev_sales in prev_results:
        prev_start = datetime.fromisoformat(prev["start_date"]).date()
        amount_at_today = 0.0
        final_amount = 0.0
        series = []
        cum_p = 0.0
        for row in prev_sales.get("by_day", []):
            try:
                d = datetime.fromisoformat(row["date"]).date()
            except ValueError:
                continue
            offset = (d - prev_start).days
            cum_p += row["amount_gbp"]
            series.append({"day_offset": offset, "value": round(cum_p, 2)})
            final_amount += row["amount_gbp"]
            if offset <= today_offset:
                amount_at_today += row["amount_gbp"]
        if amount_at_today > 0 and final_amount > 0:
            ratios.append({
                "id": prev["id"],
                "name": prev["name"],
                "amount_at_today": round(amount_at_today, 2),
                "final": round(final_amount, 2),
                "ratio": round(final_amount / amount_at_today, 3),
            })
            prev_cumul.append({"id": prev["id"], "name": prev["name"], "series": series})

    targets = {
        "good": current_launch.get("target_good", 0),
        "better": current_launch.get("target_better", 0),
        "best": current_launch.get("target_best", 0),
    }

    if not ratios:
        return {
            "today_offset": today_offset,
            "today_amount": today_amount,
            "forecast": None,
            "confidence": "low",
            "ratios": [],
            "targets": targets,
            "explanation": "No previous launches have enough data at this day-offset yet.",
            "days_to_close": days_to_close,
        }

    avg_ratio = sum(r["ratio"] for r in ratios) / len(ratios)
    forecast = round(today_amount * avg_ratio, 2)

    if today_offset < 5:
        confidence = "low"
    elif today_offset < 15:
        confidence = "medium"
    else:
        if len(ratios) >= 2:
            spread = (max(r["ratio"] for r in ratios) - min(r["ratio"] for r in ratios)) / avg_ratio
            confidence = "high" if spread < 0.25 else "medium"
        else:
            confidence = "medium"

    if forecast >= targets["best"]:
        verdict = "On pace for Best"
    elif forecast >= targets["better"]:
        verdict = "On pace for Better"
    elif forecast >= targets["good"]:
        verdict = "On pace for Good"
    else:
        verdict = "Below Good"

    return {
        "today_offset": today_offset,
        "today_amount": today_amount,
        "forecast": forecast,
        "avg_ratio": round(avg_ratio, 3),
        "confidence": confidence,
        "ratios": ratios,
        "targets": targets,
        "verdict": verdict,
        "days_to_close": days_to_close,
        "current_cumul": current_cumul,
        "prev_cumul": prev_cumul,
    }


def align_by_day_offset(by_day: list[dict], start_iso: str) -> list[dict]:
    """
    Convert a series of {date: '2026-04-01', ...} into {day_offset: 0, ...}
    relative to start_iso so multiple launches can be compared on the same axis.
    """
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).date()
    out: list[dict] = []
    for row in by_day:
        try:
            d = datetime.fromisoformat(row["date"]).date()
        except ValueError:
            continue
        offset = (d - start).days
        out.append({**row, "day_offset": offset})
    return out


# ----------------------------------------------------------- Phase breakdown
PHASE_ORDER = [
    "in_between_start",
    "early_access",
    "flash_sale",
    "webinar",
    "open_cart",
    "close_cart",
    "in_between_end",
]


def _bucket_into_phases(
    sales_by_day: list[dict],
    regs_by_day: list[dict],
    phases: dict,
) -> list[dict]:
    """
    Given a list of {date, count, amount_gbp} and {date, total} day-buckets,
    aggregate them by phase using launch.phases start/end timestamps.
    """
    # Pre-parse phase windows
    phase_windows: list[tuple[str, datetime, datetime]] = []
    for key in PHASE_ORDER:
        ph = phases.get(key) or {}
        s = ph.get("start")
        e = ph.get("end")
        if not s or not e:
            continue
        try:
            sd = datetime.fromisoformat(s.replace("Z", "+00:00"))
            ed = datetime.fromisoformat(e.replace("Z", "+00:00"))
        except ValueError:
            continue
        phase_windows.append((key, sd, ed))

    out: list[dict] = []
    for key, sd, ed in phase_windows:
        signups = 0
        revenue = 0.0
        regs = 0
        for row in sales_by_day:
            try:
                d = datetime.fromisoformat(row["date"]).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            # Phase boundaries are aligned to dates here (one whole day belongs to one phase).
            # Use phase start date as inclusive lower bound, end date as inclusive upper.
            if sd.date() <= d.date() <= ed.date():
                signups += int(row.get("count", 0))
                revenue += float(row.get("amount_gbp", 0))
        for row in regs_by_day:
            try:
                d = datetime.fromisoformat(row["date"]).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if sd.date() <= d.date() <= ed.date():
                regs += int(row.get("total", 0))
        out.append({
            "phase": key,
            "start": sd.isoformat(),
            "end": ed.isoformat(),
            "signups": signups,
            "revenue_gbp": round(revenue, 2),
            "registrations": regs,
        })
    return out


async def compute_phase_breakdown(launches_collection, current_launch: dict) -> dict:
    """
    Returns per-phase signups + revenue + registrations for the current
    launch and the previous 2 launches, so the team can compare phase-to-phase.
    Runs the 3 launches in parallel (cached fetch_sales + fetch_registrations).
    """
    cur_start = current_launch["start_date"]
    prev_cursor = launches_collection.find(
        {"start_date": {"$lt": cur_start}}, {"_id": 0}
    ).sort("start_date", -1).limit(2)
    prev_launches: list[dict] = []
    async for L in prev_cursor:
        prev_launches.append(L)

    db = launches_collection.database

    async def _bucket_for(launch: dict) -> dict:
        sales_t, regs_t = await asyncio.gather(
            cached_fetch_sales(db, launch["start_date"], launch["end_date"]),
            cached_fetch_registrations(db, launch["code"], launch["start_date"], launch["end_date"]),
            return_exceptions=True,
        )
        if isinstance(sales_t, Exception):
            sales_t = {"by_day": []}
        if isinstance(regs_t, Exception):
            regs_t = {"by_day": []}
        phases = launch.get("phases") or {}
        breakdown = _bucket_into_phases(
            sales_t.get("by_day") or [], regs_t.get("by_day") or [], phases
        )
        return {
            "id": launch["id"],
            "code": launch["code"],
            "name": launch["name"],
            "phases": breakdown,
        }

    results = await asyncio.gather(
        _bucket_for(current_launch),
        *[_bucket_for(L) for L in prev_launches],
        return_exceptions=True,
    )
    current = results[0] if not isinstance(results[0], Exception) else {
        "id": current_launch["id"], "code": current_launch["code"],
        "name": current_launch["name"], "phases": [],
    }
    previous = [r for r in results[1:] if not isinstance(r, Exception)]
    return {"current": current, "previous": previous}

