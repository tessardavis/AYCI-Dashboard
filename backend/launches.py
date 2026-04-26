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
    Pull successful Stripe charges within the date window.
    Returns daily totals + breakdown by product.
    """
    start_ts = int(datetime.fromisoformat(start_iso.replace("Z", "+00:00")).timestamp())
    end_ts = int(datetime.fromisoformat(end_iso.replace("Z", "+00:00")).timestamp())

    by_day: dict[str, dict] = {}
    by_product: dict[str, dict] = {}
    total_amount = 0
    total_count = 0
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
            r = await c.get(
                f"{STRIPE_API}/charges",
                auth=_stripe_auth(),
                params=params,
            )
            r.raise_for_status()
            body = r.json()
            charges = body.get("data", [])
            for ch in charges:
                if ch.get("status") != "succeeded" or ch.get("refunded"):
                    continue
                amount = int(ch.get("amount", 0))
                # Subtract refunded amount if any
                amount -= int(ch.get("amount_refunded", 0))
                if amount <= 0:
                    continue
                day = datetime.fromtimestamp(ch.get("created", 0), tz=timezone.utc).date().isoformat()
                desc = (ch.get("description") or "").strip()
                product = _classify_product(desc)
                by_day.setdefault(day, {"amount": 0, "count": 0, "by_product": defaultdict(int)})
                by_day[day]["amount"] += amount
                by_day[day]["count"] += 1
                by_day[day]["by_product"][product] += 1
                by_product.setdefault(product, {"amount": 0, "count": 0})
                by_product[product]["amount"] += amount
                by_product[product]["count"] += 1
                total_amount += amount
                total_count += 1
            if not body.get("has_more"):
                break
            last_starting_after = charges[-1]["id"] if charges else None
            if not last_starting_after:
                break

    by_day_list = sorted(
        [
            {
                "date": d,
                "amount_gbp": round(v["amount"] / 100.0, 2),
                "count": v["count"],
                "by_product": {p: c for p, c in v["by_product"].items()},
            }
            for d, v in by_day.items()
        ],
        key=lambda x: x["date"],
    )
    by_product_list = sorted(
        [
            {"product": p, "amount_gbp": round(v["amount"] / 100.0, 2), "count": v["count"]}
            for p, v in by_product.items()
        ],
        key=lambda x: -x["amount_gbp"],
    )

    return {
        "total_amount_gbp": round(total_amount / 100.0, 2),
        "total_count": total_count,
        "by_product": by_product_list,
        "by_day": by_day_list,
    }


def _classify_product(description: str) -> str:
    """Bucket Stripe charge descriptions into product tiers we know."""
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


# -------------------------------------------------------------- Comparison
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
