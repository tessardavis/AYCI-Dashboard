"""On-disk byte cache + HEVC→H.264 transcode for Tally-hosted videos.

Why we cache:
  Tally's CDN doesn't honour HTTP Range or expose Content-Length, which
  breaks `<video>` playback. We download each video once, write to disk,
  and serve subsequent reads with native Range support.

Why we transcode:
  iPhone records videos in HEVC (H.265). iOS Safari plays HEVC fine, but
  Chrome / Firefox / Edge can't decode it without a system codec. We
  transcode HEVC → H.264 (universally supported) once per video so coaches
  on any browser get inline playback.

Storage layout (per video) — under $PRIVATE_VIDEO_CACHE_DIR which on prod
is the persistent Render disk (`/var/data/private_video_cache`) and locally
defaults to `/tmp/private_video_cache`:
  {id}.bin        — original Tally bytes
  {id}.h264.mp4   — Chrome-playable transcode
  {id}.codec      — text marker, e.g. "h264" ("hevc" → transcode pending)

The persistent disk survives deploys + idle restarts, so we don't lose the
whole cache every time we push. Boot-warm in private_videos_store still
runs after deploy as a belt-and-braces guard against new submissions
landing while /var/data wasn't yet mounted.

Cache cap is soft — we LRU-evict by atime when total bytes exceed limit.
Transcoding runs through a global semaphore so we never hammer CPU with
multiple concurrent encodes.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.environ.get("PRIVATE_VIDEO_CACHE_DIR", "/tmp/private_video_cache"))
# Render's /tmp is hard-capped at 2 GB; instance gets EVICTED when exceeded
# (whole cache vanishes + every video re-transcodes from scratch). Keep
# headroom for the OS / other libs by capping at 1.2 GB.
MAX_CACHE_BYTES = int(os.environ.get("PRIVATE_VIDEO_CACHE_MAX_BYTES", str(int(1.2 * 1024 ** 3))))
# Headroom trimmed before each download so a near-full cache always has room to
# pull the next source video (prevents the full-disk download deadlock).
_EVICT_HEADROOM_BYTES = int(os.environ.get("PRIVATE_VIDEO_CACHE_HEADROOM_BYTES", str(2 * 1024 ** 3)))
# Durable guard: always keep at least this many bytes free on the PHYSICAL disk,
# evicting LRU regardless of MAX_CACHE_BYTES. Eviction keyed only to the cap is
# brittle (it assumes the cap matches the disk); this keys to real free space so
# the disk can't fill and deadlock downloads ("Video preparation failed").
_MIN_FREE_DISK_BYTES = int(os.environ.get("PRIVATE_VIDEO_CACHE_MIN_FREE_BYTES", str(2 * 1024 ** 3)))
# H.264 sources at or below this size are served as-is (instant playback, no
# transcode). LARGER H.264 is downscaled/compressed like HEVC so a full-size
# iPhone upload doesn't sit on the disk forever — the slow leak that refilled
# the disk after every cleanup.
_H264_KEEP_MAX_BYTES = int(os.environ.get("PRIVATE_VIDEO_H264_KEEP_MAX_BYTES", str(40 * 1024 ** 2)))

CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Log the resolved cache dir on import so any "every video re-transcodes
# after deploy" diagnosis can be answered by tailing Render logs once. If
# this prints `/tmp/...` instead of `/var/data/...` then the
# PRIVATE_VIDEO_CACHE_DIR env var isn't reaching the process.
logger.info(
    f"[pv-cache] CACHE_DIR={CACHE_DIR} MAX_CACHE_BYTES={MAX_CACHE_BYTES} "
    f"(persistent={'yes' if str(CACHE_DIR).startswith('/var/data') else 'NO — files lost on deploy'})"
)


def cache_diagnostics() -> dict:
    """Return where the cache actually is + what's currently in it. Surfaces
    via GET /api/private-videos/cache-info so the team can verify the
    persistent disk is wired without ssh-ing into Render."""
    items: list[dict] = []
    total_bytes = 0
    try:
        for p in CACHE_DIR.iterdir():
            try:
                st = p.stat()
                items.append({
                    "name": p.name,
                    "bytes": st.st_size,
                    "modified_at": st.st_mtime,
                })
                total_bytes += st.st_size
            except OSError:
                continue
    except FileNotFoundError:
        pass
    # Newest first; cap the response so big caches don't dump everything.
    items.sort(key=lambda x: x["modified_at"], reverse=True)
    disk_total = disk_free = None
    try:
        import shutil
        usage = shutil.disk_usage(str(CACHE_DIR))
        disk_total, disk_free = usage.total, usage.free
    except Exception:
        pass
    return {
        "cache_dir": str(CACHE_DIR),
        "persistent": str(CACHE_DIR).startswith("/var/data"),
        "max_cache_bytes": MAX_CACHE_BYTES,
        "current_bytes": total_bytes,
        "file_count": len(items),
        "writable": os.access(str(CACHE_DIR), os.W_OK),
        "disk_total_bytes": disk_total,
        "disk_free_bytes": disk_free,
        "partial_files": sum(1 for i in items if i["name"].endswith(".partial")),
        "recent_files": items[:20],
    }


def purge(target_free_bytes: int = 2 * 1024 ** 3) -> dict:
    """Recover from a full/over-cap cache: delete orphaned *.partial downloads,
    then LRU-evict until total is under (cap - target_free_bytes) so there's
    headroom to download again. Safe — evicted transcodes just re-download on
    next open. Returns what it freed + fresh diagnostics."""
    deleted_partials = freed = 0
    try:
        for p in CACHE_DIR.glob("*.partial"):
            try:
                sz = p.stat().st_size
                p.unlink()
                freed += sz
                deleted_partials += 1
            except OSError:
                pass
    except Exception as e:
        logger.warning(f"[pv-cache] purge partials error: {e}")
    freed += _evict_if_needed(max(0, MAX_CACHE_BYTES - target_free_bytes))
    freed += _evict_for_free_disk(target_free_bytes)  # guarantee real free disk space
    return {"deleted_partials": deleted_partials, "freed_bytes": freed, **cache_diagnostics()}

_locks: dict[str, asyncio.Lock] = {}
# Two independent transcode lanes so a coach's on-demand /video request
# never has to wait for the boot-warm / list-warm queue to drain. Each
# lane runs one transcode at a time (single-threaded ffmpeg → one CPU
# core), total parallel = 2.
#
# Without this split the worst case was: coach requests video X → joins
# the back of a 5-row boot-warm queue → waits 5×60s = 5 minutes for
# their own row to start transcoding. With the split, X starts on the
# interactive lane immediately (sharing CPU with the bg lane but still
# making progress) and finishes within one transcode budget.
_bg_transcode_sema = asyncio.Semaphore(1)
_interactive_transcode_sema = asyncio.Semaphore(1)
# Track transcode tasks so the status endpoint can report progress
_transcode_tasks: dict[str, asyncio.Task] = {}

Status = Literal["missing", "downloading", "downloaded", "transcoding", "ready", "error"]


def _ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _path_orig(item_id: str) -> Path:
    safe = "".join(c for c in item_id if c.isalnum() or c in "-_") or "x"
    return CACHE_DIR / f"{safe}.bin"


def _path_h264(item_id: str) -> Path:
    safe = "".join(c for c in item_id if c.isalnum() or c in "-_") or "x"
    return CACHE_DIR / f"{safe}.h264.mp4"


def _path_codec(item_id: str) -> Path:
    safe = "".join(c for c in item_id if c.isalnum() or c in "-_") or "x"
    return CACHE_DIR / f"{safe}.codec"


def _detect_codec(path: Path) -> str:
    """Return the video codec name (e.g. 'h264', 'hevc') or '' on failure."""
    try:
        # Run a no-op so ffmpeg only prints stream info to stderr (no decode).
        # `-loglevel info` ensures Stream lines appear; `-frames:v 0` exits
        # immediately after parsing headers.
        out = subprocess.run(
            [_ffmpeg_exe(), "-loglevel", "info", "-i", str(path), "-frames:v", "0", "-f", "null", "-"],
            capture_output=True, text=True, timeout=20,
        )
        text = out.stderr or ""
        for line in text.splitlines():
            if "Video:" in line:
                # e.g. "Stream #0:0(eng): Video: hevc (Main) (hvc1 / ...), ..."
                after = line.split("Video:", 1)[1].strip()
                codec = after.split()[0].strip(",")
                return codec.lower()
    except Exception as e:
        logger.warning(f"[pv-cache] codec detect failed: {e}")
    return ""


def _evict_if_needed(target_bytes: int | None = None) -> int:
    """LRU eviction — delete oldest-atime files until total <= target_bytes
    (default the cap). Returns bytes freed."""
    if target_bytes is None:
        target_bytes = MAX_CACHE_BYTES
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
    if total <= target_bytes:
        return 0
    files.sort()
    freed = 0
    for _, sz, p in files:
        if total <= target_bytes:
            break
        try:
            p.unlink()
            total -= sz
            freed += sz
            logger.info(f"[pv-cache] evicted {p.name} ({sz} bytes)")
        except OSError as e:
            logger.warning(f"[pv-cache] evict {p}: {e}")
    return freed


def _evict_for_free_disk(min_free_bytes: int = _MIN_FREE_DISK_BYTES) -> int:
    """LRU-evict until the PHYSICAL disk has at least `min_free_bytes` free.

    The durable fix for the recurring full-disk "Video preparation failed":
    `_evict_if_needed` trims to MAX_CACHE_BYTES, which only helps if that cap is
    set below the disk size. This evicts against real free space reported by the
    filesystem, so the disk can't fill no matter how the cap is configured."""
    import shutil
    try:
        free = shutil.disk_usage(str(CACHE_DIR)).free
    except Exception:
        return 0
    if free >= min_free_bytes:
        return 0
    files = []
    for p in CACHE_DIR.iterdir():
        if not p.is_file():
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        files.append((st.st_atime, st.st_size, p))
    files.sort()  # oldest atime first
    freed = 0
    for _, sz, p in files:
        try:
            if shutil.disk_usage(str(CACHE_DIR)).free >= min_free_bytes:
                break
        except Exception:
            break
        try:
            p.unlink()
            freed += sz
            logger.info(f"[pv-cache] evicted {p.name} for free-disk headroom ({sz} bytes)")
        except OSError as e:
            logger.warning(f"[pv-cache] free-disk evict {p}: {e}")
    return freed


async def _download(item_id: str, src_url: str) -> Path:
    """Stream Tally → disk."""
    path = _path_orig(item_id)
    if path.exists() and path.stat().st_size > 0:
        try:
            os.utime(path, None)
        except OSError:
            pass
        return path
    tmp = path.with_suffix(".bin.partial")
    async with httpx.AsyncClient(timeout=600.0, follow_redirects=True) as client:
        async with client.stream("GET", src_url) as resp:
            if resp.status_code >= 400:
                raise RuntimeError(f"upstream {resp.status_code}")
            with tmp.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=256 * 1024):
                    f.write(chunk)
    tmp.replace(path)
    logger.info(f"[pv-cache] downloaded {path.name} ({path.stat().st_size} bytes)")
    return path


async def _transcode_to_h264(item_id: str, *, priority: str = "background") -> None:
    """Run ffmpeg HEVC → H.264 in a worker thread (subprocess is blocking).
    Uses preset ultrafast so encoding stays close to real-time even on
    modest CPUs. CRF 25 is slightly compressed but visually equivalent for
    review purposes. Audio is re-encoded to AAC for compatibility.

    `priority="interactive"` uses the interactive lane (won't queue behind
    any boot-warm / list-warm transcodes currently running on the bg lane).
    """
    src = _path_orig(item_id)
    dst = _path_h264(item_id)
    tmp = dst.with_suffix(".mp4.partial")
    if not src.exists():
        raise RuntimeError("source missing")

    cmd = [
        _ffmpeg_exe(),
        "-y",  # overwrite
        "-loglevel", "error",
        # Single thread — Render's instance has very limited CPU and the
        # default ffmpeg behaviour (use all cores) was saturating it,
        # making concurrent HTTP requests (e.g. the /video/status polling)
        # take 2-4s instead of the usual <100ms. Slower per-transcode but
        # the whole app stays responsive while encoding runs.
        "-threads", "1",
        "-i", str(src),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "30",                # was 28 — still fine for talking-head review, ~20% smaller / faster
        # Cap longest dimension at 854. Was 1280; halved pixel count for
        # an iPhone 1080p source which roughly halves single-thread
        # encode time on Render's 1-CPU Standard plan. Landscape
        # 1920x1080 → 854x480; portrait 1080x1920 → 480x854. EDTV-class
        # resolution — coaches reviewing talking-head answers don't
        # need full HD detail and the win on cold-load is significant.
        "-vf", "scale=854:854:force_original_aspect_ratio=decrease",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "64k",               # was 96k — voice-only, perceptually identical
        "-movflags", "+faststart",
        "-f", "mp4",  # filename ends in .partial so format must be explicit
        str(tmp),
    ]

    sema = _interactive_transcode_sema if priority == "interactive" else _bg_transcode_sema
    async with sema:
        logger.info(f"[pv-cache] transcoding {item_id} ({priority})…")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise RuntimeError(f"ffmpeg failed: {stderr.decode(errors='replace')[:500]}")
    tmp.replace(dst)
    logger.info(f"[pv-cache] transcoded {dst.name} ({dst.stat().st_size} bytes)")
    # Free disk: the H.264 copy is what we serve from now on. Keeping the
    # original .bin doubles the per-video footprint and contributed to
    # /tmp eviction on Render's 2 GB cap. (If we ever need to re-transcode
    # we re-download from Tally — rare.)
    try:
        _path_orig(item_id).unlink(missing_ok=True)
    except OSError as e:
        logger.info(f"[pv-cache] could not remove original after transcode: {e}")


def get_status(item_id: str) -> Status:
    orig = _path_orig(item_id)
    h264 = _path_h264(item_id)
    codec_marker = _path_codec(item_id)
    task = _transcode_tasks.get(item_id)

    if h264.exists() and h264.stat().st_size > 0:
        return "ready"
    if codec_marker.exists() and codec_marker.read_text().strip() == "h264":
        # Original is already H.264 — playable as-is, no transcode needed
        return "ready"
    if task and not task.done():
        return "transcoding"
    if orig.exists() and orig.stat().st_size > 0:
        return "downloaded"
    if item_id in _locks and _locks[item_id].locked():
        return "downloading"
    return "missing"


def playable_path(item_id: str) -> Path | None:
    """Return the path the proxy should serve from. Prefers transcoded
    H.264; falls back to original if codec is already H.264-compatible."""
    h264 = _path_h264(item_id)
    if h264.exists() and h264.stat().st_size > 0:
        return h264
    orig = _path_orig(item_id)
    codec_marker = _path_codec(item_id)
    if (
        orig.exists() and orig.stat().st_size > 0
        and codec_marker.exists() and codec_marker.read_text().strip() == "h264"
    ):
        return orig
    return None


async def prepare(item_id: str, src_url: str, *, priority: str = "background", force: bool = False) -> None:
    """Idempotent end-to-end: download → detect codec → transcode if HEVC.
    Concurrent calls share a per-id Lock so we don't double-download.

    `priority="interactive"` routes the transcode to the dedicated
    interactive lane so a coach's on-demand /video request doesn't queue
    behind the boot-warm batch.

    `force=True` re-runs the transcode even when a cached file already
    exists — used by the admin recompress endpoint to apply new
    transcode settings (resolution/CRF) to previously-cached rows.
    """
    lock = _locks.setdefault(item_id, asyncio.Lock())
    async with lock:
        # Re-check inside the lock
        if playable_path(item_id) and not force:
            return
        # Force path: drop the existing transcode so we re-download +
        # re-encode. We KEEP the codec marker so the codec-detection step
        # below can be skipped on a re-run.
        if force:
            try:
                _path_h264(item_id).unlink(missing_ok=True)
            except OSError:
                pass
        # Make room BEFORE downloading. Eviction used to run only AFTER the
        # download, so once the disk filled, every download failed first and
        # eviction never ran — a deadlock. Trim to leave headroom up front.
        try:
            _evict_if_needed(max(0, MAX_CACHE_BYTES - _EVICT_HEADROOM_BYTES))
            _evict_for_free_disk()  # also guarantee real free space on the disk
        except Exception as e:
            logger.warning(f"[pv-cache] pre-download eviction error: {e}")
        try:
            await _download(item_id, src_url)
        except Exception:
            logger.exception(f"[pv-cache] download failed {item_id}")
            raise
        # Detect codec & decide whether to transcode
        codec = _detect_codec(_path_orig(item_id))
        if not codec:
            codec = "unknown"
        try:
            _path_codec(item_id).write_text(codec)
        except OSError:
            pass
        if codec == "h264":
            # Small H.264 → serve as-is (instant, no transcode). Large H.264 →
            # fall through and compress, so a full-size upload doesn't linger on
            # disk. playable_path serves the original meanwhile, so there's no
            # 502 even while the background compress runs (or if it fails).
            try:
                if _path_orig(item_id).stat().st_size <= _H264_KEEP_MAX_BYTES:
                    return
            except OSError:
                return
            logger.info(f"[pv-cache] {item_id} is large H.264 — compressing to cap disk footprint")

    # Transcode outside the per-id lock so other items can download
    # concurrently. Fire-and-forget so the caller doesn't block.
    if _path_h264(item_id).exists() and not force:
        return
    if item_id in _transcode_tasks and not _transcode_tasks[item_id].done():
        return
    _transcode_tasks[item_id] = asyncio.create_task(
        _transcode_to_h264(item_id, priority=priority)
    )

    try:
        _evict_if_needed()
    except Exception as e:
        logger.warning(f"[pv-cache] eviction error: {e}")


async def ensure_ready(item_id: str, src_url: str, *, priority: str = "background") -> Path:
    """Block until a playable file is available. Used when the user
    actually requests bytes (vs `prepare` which just kicks things off).
    Pass `priority="interactive"` so the transcode skips the bg queue."""
    await prepare(item_id, src_url, priority=priority)
    p = playable_path(item_id)
    if p:
        return p
    # Wait on the transcode task if it's running
    task = _transcode_tasks.get(item_id)
    if task:
        await task
    p = playable_path(item_id)
    if not p:
        raise RuntimeError("video preparation failed")
    return p
