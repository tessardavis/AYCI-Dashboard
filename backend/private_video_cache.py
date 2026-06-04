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

CACHE_DIR.mkdir(parents=True, exist_ok=True)

_locks: dict[str, asyncio.Lock] = {}
# Two concurrent transcodes. Each is single-threaded (-threads 1), so total
# CPU footprint is 2 threads — fits Render Standard with headroom. Halves
# the worst-case "row N in queue" wait time for coaches.
_transcode_sema = asyncio.Semaphore(2)
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


def _evict_if_needed() -> None:
    """LRU eviction — delete oldest atime files until back under cap."""
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
    files.sort()
    for _, sz, p in files:
        if total <= MAX_CACHE_BYTES:
            break
        try:
            p.unlink()
            total -= sz
            logger.info(f"[pv-cache] evicted {p.name} ({sz} bytes)")
        except OSError as e:
            logger.warning(f"[pv-cache] evict {p}: {e}")


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


async def _transcode_to_h264(item_id: str) -> None:
    """Run ffmpeg HEVC → H.264 in a worker thread (subprocess is blocking).
    Uses preset ultrafast so encoding stays close to real-time even on
    modest CPUs. CRF 25 is slightly compressed but visually equivalent for
    review purposes. Audio is re-encoded to AAC for compatibility."""
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
        "-crf", "28",                # was 25 — indistinguishable for talking-head review
        # Cap longest dimension at 1280. Fits within a 1280x1280 box,
        # only downscales (force_original_aspect_ratio=decrease), preserves
        # aspect ratio. Landscape 1920x1080 → 1280x720; portrait
        # 1080x1920 → 720x1280. iPhones record 1080p; coaches don't need
        # full resolution for review.
        "-vf", "scale=1280:1280:force_original_aspect_ratio=decrease",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "96k",               # was 128k — voice-only content fine at 96
        "-movflags", "+faststart",
        "-f", "mp4",  # filename ends in .partial so format must be explicit
        str(tmp),
    ]

    async with _transcode_sema:
        logger.info(f"[pv-cache] transcoding {item_id}…")
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


async def prepare(item_id: str, src_url: str) -> None:
    """Idempotent end-to-end: download → detect codec → transcode if HEVC.
    Concurrent calls share a per-id Lock so we don't double-download."""
    lock = _locks.setdefault(item_id, asyncio.Lock())
    async with lock:
        # Re-check inside the lock
        if playable_path(item_id):
            return
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
            return  # playable as-is

    # Transcode outside the per-id lock so other items can download
    # concurrently. Fire-and-forget so the caller doesn't block.
    if _path_h264(item_id).exists():
        return
    if item_id in _transcode_tasks and not _transcode_tasks[item_id].done():
        return
    _transcode_tasks[item_id] = asyncio.create_task(_transcode_to_h264(item_id))

    try:
        _evict_if_needed()
    except Exception as e:
        logger.warning(f"[pv-cache] eviction error: {e}")


async def ensure_ready(item_id: str, src_url: str) -> Path:
    """Block until a playable file is available. Used when the user
    actually requests bytes (vs `prepare` which just kicks things off)."""
    await prepare(item_id, src_url)
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
