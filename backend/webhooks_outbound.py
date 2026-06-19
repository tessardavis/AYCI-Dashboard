"""
Outbound webhook dispatcher — emits column-change events to subscribed URLs.

Replaces the Monday "Specific Column Value Changed" trigger used by ~12 zaps.
Each subscribed zap re-points its trigger to "Webhooks by Zapier — Catch Hook"
and registers the catch-hook URL here via the admin endpoint.

Mongo collection: `dashboard_webhook_subscriptions`
    {
      _id: uuid,
      name: human label,
      column: "tier" | "interview_date" | ... (must be a PROTECTED_FIELDS field),
      url: "https://hooks.zapier.com/...",
      active: bool,
      created_at: ISO,
      created_by: email,
    }

Emission is best-effort and fire-and-forget: failures are logged but never
break the originating write. No retries in v1 — Zapier's catch hook is
reliable enough for the use case and the dashboard remains source of truth.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


async def _post_one(url: str, payload: dict) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(url, json=payload)
            if r.status_code >= 300:
                logger.warning(
                    f"[webhooks-out] {url} returned {r.status_code}: {r.text[:200]}"
                )
                return False
            return True
    except Exception as e:
        logger.warning(f"[webhooks-out] {url} failed: {e}")
        return False


async def notify_column_changes(
    db,
    *,
    item_id: str,
    fields_changed: dict[str, Any],
    student: dict,
) -> int:
    """For each changed column, POST to every active subscriber.

    `fields_changed` is the {field: new_value} dict the write applied.
    `student` is the minimal post-write row (used to populate the payload).

    Returns the number of webhook POSTs successfully delivered. Failures
    are logged but do not propagate — the originating write succeeded
    regardless."""
    if not fields_changed:
        return 0

    cursor = db.dashboard_webhook_subscriptions.find(
        {"column": {"$in": list(fields_changed.keys())}, "active": True},
        {"_id": 0, "url": 1, "column": 1, "name": 1},
    )
    subs = [s async for s in cursor]
    if not subs:
        return 0

    now = datetime.now(timezone.utc).isoformat()

    # Group POSTs by URL so two changes to the same subscriber don't fire
    # twice — bundle into one payload with all changed columns.
    by_url: dict[str, list[dict]] = {}
    for s in subs:
        by_url.setdefault(s["url"], []).append(s)

    payloads_to_send: list[tuple[str, dict]] = []
    for url, sub_list in by_url.items():
        changed_for_this_sub = {
            s["column"]: fields_changed[s["column"]]
            for s in sub_list
            if s["column"] in fields_changed
        }
        payload = {
            "event": "column_changed",
            "item_id": item_id,
            "changed": changed_for_this_sub,
            "student": {
                "id": student.get("_id") or student.get("id") or item_id,
                "email": student.get("email"),
                "circle_email": student.get("circle_email"),
                "name": student.get("name"),
                "first_name": student.get("first_name"),
                "surname": student.get("surname"),
                "tier": student.get("tier"),
                "cohort_joined": student.get("cohort_joined"),
                "interview_date": student.get("interview_date"),
            },
            "emitted_at": now,
        }
        payloads_to_send.append((url, payload))

    results = await asyncio.gather(
        *[_post_one(url, p) for url, p in payloads_to_send],
        return_exceptions=True,
    )
    delivered = sum(1 for r in results if r is True)
    logger.info(
        f"[webhooks-out] item={item_id} delivered={delivered}/{len(payloads_to_send)} "
        f"columns={list(fields_changed.keys())}"
    )
    return delivered


async def active_subscription_columns(db) -> set[str]:
    """The set of columns that currently have at least one active subscriber.
    The mirror uses this to decide whether to bother diffing Monday-side
    changes at all — when nothing is subscribed (the common case during
    transition) the mirror-emit bridge is a complete no-op."""
    cols = await db.dashboard_webhook_subscriptions.distinct("column", {"active": True})
    return {c for c in cols if c}


def changed_fields_diff(before: Optional[dict], after_set: dict) -> dict:
    """Return only the fields in `after_set` whose value actually differs from
    `before`. Lets the dispatcher skip no-op events (e.g. setting `tier` to
    the value it already had)."""
    if before is None:
        return dict(after_set)
    diff = {}
    for k, v in after_set.items():
        if before.get(k) != v:
            diff[k] = v
    return diff
