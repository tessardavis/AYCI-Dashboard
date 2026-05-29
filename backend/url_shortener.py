"""
Tiny URL shortener for outbound coach messages.

Tally video URLs land at storage.tally.so with multi-hundred-character access
tokens — pasting them into a Circle DM looks awful. We shorten them via is.gd
(free, no auth, stable since 2008) and cache the result in Mongo so the same
long URL always returns the same short URL.

Cache is in `db.url_shortlinks` keyed by long URL. We never hit is.gd twice
for the same input.

Usage:
    from url_shortener import shorten
    short = await shorten(db, "https://storage.tally.so/...very-long...")
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

# is.gd is free + no auth + has been stable since 2008. If it ever goes
# away or we hit a rate limit, swap the implementation in _create_short_url.
IS_GD_ENDPOINT = "https://is.gd/create.php"


async def _create_short_url(long_url: str) -> str | None:
    """Hit is.gd. Returns the short URL (e.g. "https://is.gd/abc123") or
    None if shortening fails (caller falls back to the long URL)."""
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(
                IS_GD_ENDPOINT,
                params={"format": "simple", "url": long_url},
            )
        if r.status_code != 200:
            logger.info(f"[shortener] is.gd returned {r.status_code} for url len {len(long_url)}")
            return None
        body = (r.text or "").strip()
        if not body.startswith("http"):
            logger.info(f"[shortener] is.gd unexpected body: {body[:120]}")
            return None
        return body
    except Exception as e:
        logger.info(f"[shortener] is.gd failed: {e}")
        return None


async def shorten(db, long_url: str) -> str:
    """Return a short URL for `long_url`, or the original URL on failure.

    Cached in db.url_shortlinks so repeated calls (and repeated previews of
    the same row) return the same short URL without re-hitting is.gd."""
    if not long_url or not isinstance(long_url, str):
        return long_url or ""
    url = long_url.strip()
    if not url:
        return ""
    # Already short — don't waste a roundtrip.
    if len(url) <= 50 and "is.gd" in url:
        return url

    cached = await db.url_shortlinks.find_one(
        {"long_url": url}, {"_id": 0, "short_url": 1}
    )
    if cached and cached.get("short_url"):
        return cached["short_url"]

    short = await _create_short_url(url)
    if not short:
        # Don't cache failures — next call retries.
        return url

    await db.url_shortlinks.update_one(
        {"long_url": url},
        {"$set": {
            "long_url": url,
            "short_url": short,
            "created_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )
    return short
