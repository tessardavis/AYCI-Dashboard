"""Circle Admin API usage meter + circuit breaker.

Circle's Admin API has a 30,000 requests/month included allowance, then
$0.002/call. The billing cycle resets on the 2nd of each month. Circle's own
alerting stops at 120% of the limit by design, so the guardrail has to live
here. A bug once ran one endpoint to ~1.9M calls (~$7k); this module makes that
impossible to repeat silently.

What it does:
  - SINGLE CHOKEPOINT: every Admin API call goes through `circle_admin_request`.
    Nothing reaches the Admin API without being counted.
  - PERSISTENT COUNTER: total + per-endpoint for the current billing cycle,
    flushed to Mongo (`circle_usage`), reloaded on startup, auto-reset on the 2nd.
  - RATE MONITOR: per-minute buckets → last-hour / last-24h counts (fast tripwire).
  - TWO LAYERS: alert early (Slack), then hard-stop NON-ESSENTIAL calls when a
    ceiling is crossed. Essential (user-facing) calls are exempt but logged.

Scope: the Admin API only (the 30k/$0.002 surface). Headless/DM calls are billed
separately and are not metered here.

Thresholds are env-overridable - see the constants below.
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


# ---- thresholds (env-overridable) ----------------------------------------
# Baseline after recent fixes: ~37 calls/hour, ~900/day, ~27k/month.
MONTHLY_ALLOWANCE = _int_env("CIRCLE_MONTHLY_ALLOWANCE", 30_000)   # Circle's included allowance
RATE_ALERT_PER_HOUR = _int_env("CIRCLE_RATE_ALERT_PER_HOUR", 400)  # ~11x baseline → early alert
RATE_TRIP_PER_HOUR = _int_env("CIRCLE_RATE_TRIP_PER_HOUR", 900)    # ~24x baseline → trip breaker
HARD_CEILING = _int_env("CIRCLE_HARD_CEILING", 60_000)             # cumulative trip (≈$60 worst case)
# Cumulative early-warning levels (comma-separated env override).
_levels_env = os.environ.get("CIRCLE_CUMULATIVE_ALERT_LEVELS", "").strip()
try:
    CUMULATIVE_ALERT_LEVELS = sorted(int(x) for x in _levels_env.split(",") if x.strip()) or [30_000, 50_000]
except ValueError:
    CUMULATIVE_ALERT_LEVELS = [30_000, 50_000]
ALERT_CHANNEL = os.environ.get("CIRCLE_USAGE_ALERT_CHANNEL", "").strip() or "#fulfillment-team"

_FLUSH_EVERY_SECONDS = 30
_HTTP_TIMEOUT = 30


class CircleBudgetExceeded(RuntimeError):
    """Raised when a NON-essential Admin call is blocked because the breaker is
    tripped. Callers (background jobs) should catch and skip gracefully."""

    def __init__(self, endpoint: str, reason: str):
        self.endpoint = endpoint
        self.reason = reason
        super().__init__(f"Circle Admin breaker tripped ({reason}) - blocked non-essential call to {endpoint}")


# ---- in-process state ----------------------------------------------------
_db = None                     # set by init()
_cycle_id: str | None = None
_cycle_start: datetime | None = None
_cycle_end: datetime | None = None
_total = 0
_by_endpoint: dict[str, int] = defaultdict(int)
_minute_buckets: dict[int, int] = {}        # epoch-minute → count (last 24h)
_breaker = {"tripped": False, "reason": None, "at": None}
_alerted: set[str] = set()                  # dedup keys for this process/cycle
_last_flush = 0.0
_client: httpx.AsyncClient | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cycle_bounds(now: datetime):
    """Billing cycle runs 2nd → 2nd (UTC). Returns (cycle_id, start, end)."""
    if now.day >= 2:
        start = now.replace(day=2, hour=0, minute=0, second=0, microsecond=0)
    else:
        last_prev = now.replace(day=1) - timedelta(days=1)
        start = last_prev.replace(day=2, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 \
        else start.replace(month=start.month + 1)
    return start.strftime("%Y-%m-%d"), start, end


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
    return _client


async def init(db) -> None:
    """Load the current cycle's counters from Mongo on startup so the cap and
    breaker survive restarts."""
    global _db
    _db = db
    await _ensure_cycle(load=True)


async def _ensure_cycle(load: bool = False) -> None:
    """Roll the in-memory counters to the current billing cycle. Resets on the
    2nd. `load=True` pulls the persisted doc (startup / first call)."""
    global _cycle_id, _cycle_start, _cycle_end, _total, _by_endpoint, _breaker, _alerted
    cid, start, end = _cycle_bounds(_now())
    if cid == _cycle_id and not load:
        return
    if cid != _cycle_id:
        _cycle_id, _cycle_start, _cycle_end = cid, start, end
        _total = 0
        _by_endpoint = defaultdict(int)
        _breaker = {"tripped": False, "reason": None, "at": None}
        _alerted = set()
    if load and _db is not None:
        doc = await _db.circle_usage.find_one({"_id": cid})
        if doc:
            _total = int(doc.get("total") or 0)
            _by_endpoint = defaultdict(int, {k: int(v) for k, v in (doc.get("by_endpoint") or {}).items()})
            b = doc.get("breaker") or {}
            _breaker = {"tripped": bool(b.get("tripped")), "reason": b.get("reason"), "at": b.get("at")}
        # Re-arm the cumulative breaker from the restored total (sticky within cycle).
        if _total >= HARD_CEILING and not _breaker["tripped"]:
            _trip("cumulative", flush=False)


async def _flush(force: bool = False) -> None:
    global _last_flush
    if _db is None:
        return
    import time as _time
    if not force and (_time.monotonic() - _last_flush) < _FLUSH_EVERY_SECONDS:
        return
    _last_flush = _time.monotonic()
    try:
        await _db.circle_usage.update_one(
            {"_id": _cycle_id},
            {"$set": {
                "_id": _cycle_id,
                "cycle_start": _cycle_start, "cycle_end": _cycle_end,
                "total": _total, "by_endpoint": dict(_by_endpoint),
                "breaker": _breaker, "updated_at": _now(),
            }},
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"[circle-meter] flush failed: {e}")


def _prune_buckets(now_min: int) -> None:
    cutoff = now_min - 24 * 60
    for m in [m for m in _minute_buckets if m < cutoff]:
        _minute_buckets.pop(m, None)


def _rate(minutes: int) -> int:
    now_min = int(_now().timestamp() // 60)
    return sum(c for m, c in _minute_buckets.items() if m > now_min - minutes)


async def _alert(key: str, message: str) -> None:
    """Slack alert, deduped by key (so a sustained runaway alerts once, not every call)."""
    if key in _alerted:
        return
    _alerted.add(key)
    logger.warning(f"[circle-meter] ALERT {key}: {message}")
    if _db is None:
        return
    try:
        import slack_dm
        await slack_dm.post_to_channel(_db, ALERT_CHANNEL, message)
    except Exception as e:
        logger.warning(f"[circle-meter] alert post failed: {e}")


def _trip(reason: str, flush: bool = True) -> None:
    if not _breaker["tripped"]:
        _breaker.update({"tripped": True, "reason": reason, "at": _now()})
        logger.error(f"[circle-meter] BREAKER TRIPPED ({reason}) total={_total} hour={_rate(60)}")


async def _record(endpoint: str) -> None:
    """Count one Admin call + evaluate the tripwires."""
    global _total
    _total += 1
    _by_endpoint[endpoint] += 1
    now_min = int(_now().timestamp() // 60)
    _minute_buckets[now_min] = _minute_buckets.get(now_min, 0) + 1
    _prune_buckets(now_min)

    hour = _rate(60)
    # --- cumulative warnings + ceiling ---
    for lvl in CUMULATIVE_ALERT_LEVELS:
        if _total >= lvl and _total - 1 < lvl:
            await _alert(
                f"cum:{_cycle_id}:{lvl}",
                f":warning: *Circle Admin API*: {_total:,} calls this cycle "
                f"(crossed {lvl:,}; allowance {MONTHLY_ALLOWANCE:,}, hard cap {HARD_CEILING:,}). "
                f"Last hour: {hour}. Check `/api/admin/circle-usage`.",
            )
    if _total >= HARD_CEILING and not _breaker["tripped"]:
        _trip("cumulative")
        await _alert(
            f"trip-cum:{_cycle_id}",
            f":rotating_light: *Circle Admin API breaker TRIPPED* - cumulative {_total:,} calls "
            f"≥ hard cap {HARD_CEILING:,} this cycle. Non-essential Circle calls are now paused "
            f"until the 2nd or a manual reset (`POST /api/admin/circle-usage/reset-breaker`).",
        )
    # --- rate alert + trip ---
    if hour >= RATE_TRIP_PER_HOUR and not _breaker["tripped"]:
        _trip("rate")
        await _alert(
            f"trip-rate:{_cycle_id}:{now_min // 60}",
            f":rotating_light: *Circle Admin API breaker TRIPPED* - {hour} calls in the last hour "
            f"(≥ {RATE_TRIP_PER_HOUR}/hr, baseline ~37/hr). Non-essential Circle calls paused. "
            f"Investigate, then `POST /api/admin/circle-usage/reset-breaker`.",
        )
    elif hour >= RATE_ALERT_PER_HOUR:
        await _alert(
            f"rate:{_cycle_id}:{now_min // 60}",
            f":warning: *Circle Admin API*: elevated rate - {hour} calls in the last hour "
            f"(alert at {RATE_ALERT_PER_HOUR}/hr, baseline ~37/hr). Cycle total {_total:,}. "
            f"Top: {_top_endpoints(3)}.",
        )

    await _flush()


def _top_endpoints(n: int) -> str:
    top = sorted(_by_endpoint.items(), key=lambda kv: kv[1], reverse=True)[:n]
    return ", ".join(f"{k} ({v:,})" for k, v in top) or "-"


async def circle_admin_request(method: str, url: str, *, endpoint: str,
                               essential: bool = False, **kwargs) -> httpx.Response:
    """THE single chokepoint for Circle Admin API calls. Every Admin request must
    go through here. `endpoint` is a short label for the per-endpoint counter
    (e.g. 'community_members', 'posts', 'comments'). `essential=True` exempts a
    user-facing call from the breaker (it still gets counted + logged).

    Raises CircleBudgetExceeded for a non-essential call while the breaker is
    tripped - callers in background jobs should catch and skip."""
    await _ensure_cycle()
    if _breaker["tripped"] and not essential:
        raise CircleBudgetExceeded(endpoint, _breaker["reason"] or "tripped")
    if _breaker["tripped"] and essential:
        logger.warning(f"[circle-meter] breaker tripped but allowing ESSENTIAL call to {endpoint}")
    try:
        resp = await _get_client().request(method, url, **kwargs)
        return resp
    finally:
        # Count the attempt regardless of outcome - a runaway of failing calls
        # still hammers (and may bill) Circle.
        try:
            await _record(endpoint)
        except Exception as e:
            logger.warning(f"[circle-meter] record failed: {e}")


async def reset_breaker(by: str = "manual") -> dict:
    """Re-arm the breaker after a runaway is fixed (clears rate + cumulative trip
    for the rest of the cycle - note a cumulative trip will re-trip if total is
    still ≥ ceiling and more calls come in)."""
    _breaker.update({"tripped": False, "reason": None, "at": None})
    # Let the cumulative alert fire again only if it crosses anew.
    await _flush(force=True)
    logger.warning(f"[circle-meter] breaker reset by {by}")
    return {"ok": True, "breaker": dict(_breaker)}


def status() -> dict:
    return {
        "cycle_id": _cycle_id,
        "cycle_start": _cycle_start.isoformat() if _cycle_start else None,
        "cycle_end": _cycle_end.isoformat() if _cycle_end else None,
        "total": _total,
        "allowance": MONTHLY_ALLOWANCE,
        "hard_ceiling": HARD_CEILING,
        "pct_of_allowance": round(100 * _total / MONTHLY_ALLOWANCE, 1) if MONTHLY_ALLOWANCE else None,
        "rate_last_hour": _rate(60),
        "rate_last_24h": _rate(24 * 60),
        "by_endpoint": dict(sorted(_by_endpoint.items(), key=lambda kv: kv[1], reverse=True)),
        "breaker": {
            "tripped": _breaker["tripped"],
            "reason": _breaker["reason"],
            "at": _breaker["at"].isoformat() if isinstance(_breaker["at"], datetime) else _breaker["at"],
        },
        "thresholds": {
            "rate_alert_per_hour": RATE_ALERT_PER_HOUR,
            "rate_trip_per_hour": RATE_TRIP_PER_HOUR,
            "cumulative_alert_levels": CUMULATIVE_ALERT_LEVELS,
            "hard_ceiling": HARD_CEILING,
        },
        "alert_channel": ALERT_CHANNEL,
    }
