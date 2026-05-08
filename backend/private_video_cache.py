"""On-disk byte cache for Tally-hosted private-tier videos.

Tally's CDN doesn't honour HTTP Range or expose Content-Length, which
breaks `<video>` playback in browsers (especially iOS Safari). We download
each video once, write it to local disk, and serve subsequent reads
straight from disk where Range support is native + the total file size is
known up-front.

The cache lives at PRIVATE_VIDEO_CACHE_DIR (defaults to /tmp/private_video_cache)
with a soft cap of MAX_CACHE_BYTES — when exceeded we LRU-evict by mtime.

Concurrency: per-id `asyncio.Lock` so only one download runs even when
multiple coaches click the same row simultaneously.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.environ.get("PRIVATE_VIDEO_CACHE_DIR", "/tmp/private_video_cache"))
MAX_CACHE_BYTES = int(os.environ.get("PRIVATE_VIDEO_CACHE_MAX_BYTES", str(10 * 1024 ** 3)))  # 10 GB

CACHE_DIR.mkdir(parents=True, exist_ok=True)

_locks: dict[str, asyncio.Lock] = {}


def _path_for(item_id: str) -> Path:
    safe = "".join(c for c in item_id if c.isalnum() or c in "-_") or "x"
    return CACHE_DIR / f"{safe}.bin"


def _evict_if_needed() -> None:
    """LRU eviction — delete oldest atime files until we're back under cap."""
    files = []
    total = 0
    for p in CACHE_DIR.iterdir():
        if not p.is_file():
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        files.append((st.st_atime, st.st_size, p))
        total += st.st_size
    if total <= MAX_CACHE_BYTES:
        return
    files.sort()  # oldest atime first
    for _, sz, p in files:
        if total <= MAX_CACHE_BYTES:
            break
        try:
            p.unlink()
            total -= sz
            logger.info(f"[pv-cache] evicted {p.name} ({sz} bytes)")
        except OSError as e:
            logger.warning(f"[pv-cache] failed to evict {p}: {e}")


async def ensure_cached(item_id: str, src_url: str) -> Path:
    """Download `src_url` to disk if not already cached. Returns the cached
    file path. Concurrent calls for the same id wait on a shared Lock."""
    path = _path_for(item_id)
    if path.exists() and path.stat().st_size > 0:
        # Touch atime so LRU eviction respects "recently accessed".
        try:
            os.utime(path, None)
        except OSError:
            pass
        return path

    lock = _locks.setdefault(item_id, asyncio.Lock())
    async with lock:
        # Re-check after acquiring the lock — another caller may have done it.
        if path.exists() and path.stat().st_size > 0:
            return path
        tmp = path.with_suffix(".bin.partial")
        try:
            async with httpx.AsyncClient(timeout=600.0, follow_redirects=True) as client:
                async with client.stream("GET", src_url) as resp:
                    if resp.status_code >= 400:
                        raise RuntimeError(f"upstream returned {resp.status_code}")
                    with tmp.open("wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=256 * 1024):
                            f.write(chunk)
            tmp.replace(path)
            logger.info(f"[pv-cache] cached {path.name} ({path.stat().st_size} bytes)")
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
    # Best-effort eviction outside the lock
    try:
        _evict_if_needed()
    except Exception as e:
        logger.warning(f"[pv-cache] eviction error: {e}")
    return path
