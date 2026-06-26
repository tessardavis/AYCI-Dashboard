"""
In-house URL shortener for outbound coach messages.

Tally video URLs land at storage.tally.so with multi-hundred-character access
tokens - pasting those into a Circle DM looks awful. We mint a short code,
cache it in Mongo, and serve a 302 redirect from /v/{code} on the backend.

Was previously backed by is.gd; that silently failed often enough that the
Circle DMs went out with the full long URL anyway. Self-hosting removes the
external dependency.

Schema (db.url_shortlinks):
  {
    code: "abc123",          # short code (8 chars, base62-ish)
    long_url: "https://...", # the target - unique index on this
    created_at: ISODate,
  }

Usage:
    from url_shortener import shorten
    short = await shorten(db, "https://storage.tally.so/...very-long...")
    # → "https://ayci-dashboard.onrender.com/v/abc123"
"""
from __future__ import annotations

import logging
import os
import secrets
import string
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Public origin that serves the /v/{code} redirect. Render is the canonical
# host; can be overridden via env var if we move the redirect to a shorter
# custom domain later.
SHORTLINK_ORIGIN = os.environ.get(
    "SHORTLINK_ORIGIN",
    "https://ayci-dashboard.onrender.com",
).rstrip("/")

_ALPHABET = string.ascii_letters + string.digits  # 62 chars
_CODE_LEN = 8  # 62^8 ≈ 2e14 - plenty


def _new_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LEN))


async def shorten(db, long_url: str) -> str:
    """Return a short URL for `long_url`, or the original URL on failure.

    Idempotent per long URL - repeated calls return the same short URL.
    Cached in db.url_shortlinks (unique index on long_url)."""
    if not long_url or not isinstance(long_url, str):
        return long_url or ""
    url = long_url.strip()
    if not url:
        return ""
    # Already one of our shortlinks (or shorter than a code would be).
    if url.startswith(f"{SHORTLINK_ORIGIN}/v/"):
        return url

    cached = await db.url_shortlinks.find_one(
        {"long_url": url}, {"_id": 0, "code": 1}
    )
    if cached and cached.get("code"):
        return f"{SHORTLINK_ORIGIN}/v/{cached['code']}"

    # Generate a fresh code. Retry a couple of times on the (vanishingly
    # unlikely) collision.
    for _ in range(5):
        code = _new_code()
        try:
            await db.url_shortlinks.insert_one({
                "code": code,
                "long_url": url,
                "created_at": datetime.now(timezone.utc),
            })
            return f"{SHORTLINK_ORIGIN}/v/{code}"
        except Exception as e:
            # Likely duplicate key on `code` - retry. If on `long_url`,
            # another writer beat us; re-read the cached value.
            if "duplicate key" in str(e).lower():
                cached = await db.url_shortlinks.find_one(
                    {"long_url": url}, {"_id": 0, "code": 1}
                )
                if cached and cached.get("code"):
                    return f"{SHORTLINK_ORIGIN}/v/{cached['code']}"
                # else: code collision; loop to try a new code
                continue
            logger.info(f"[shortener] insert failed: {e}")
            return url
    logger.info("[shortener] couldn't allocate a unique code in 5 tries; returning long url")
    return url
