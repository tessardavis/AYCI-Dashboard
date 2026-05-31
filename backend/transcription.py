"""
OpenAI Whisper-backed transcription for Private Video submissions.

Each Tally video gets transcribed once and the result is cached on the row
(db.private_video_submissions.transcript). Coaches see the text alongside
the video in the Edit modal so they can triage / scan / search without
watching every full submission.

Pipeline per video:
  1. Wait for the original Tally bytes on disk (pv_cache.prepare).
  2. Extract the audio track (ffmpeg, no re-encode — fast, tiny output).
     Most iPhone videos are HEVC + AAC; Whisper accepts AAC in M4A.
  3. Send to OpenAI Whisper API (whisper-1, verbose_json for segments).
  4. Persist {text, segments, model, generated_at} on the Mongo row.

Cost: ~$0.006/min of audio. 2-3min videos = ~£0.01 each.

Configuration:
  OPENAI_API_KEY — required, must start with `sk-...`. If missing, the
  module gracefully no-ops (no transcript generated, dashboard shows
  "Transcription not configured").
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

WHISPER_MODEL = "whisper-1"
# Whisper API hard limit. Audio-only extraction usually keeps us well under
# this even for ~5min videos.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _api_key() -> Optional[str]:
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    return key or None


def configured() -> bool:
    return _api_key() is not None


async def _extract_audio(video_path: Path) -> Optional[Path]:
    """Copy the audio track out to M4A (no re-encode). Returns the audio
    path, or None if extraction fails."""
    import private_video_cache as pv_cache
    audio_path = video_path.with_suffix(".audio.m4a")
    if audio_path.exists() and audio_path.stat().st_size > 0:
        return audio_path
    tmp = audio_path.with_suffix(".m4a.partial")
    cmd = [
        pv_cache._ffmpeg_exe(),
        "-y",
        "-loglevel", "error",
        "-i", str(video_path),
        "-vn",           # drop video
        "-c:a", "copy",  # don't re-encode audio
        "-f", "mp4",
        str(tmp),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        # Some files don't have a copyable AAC track. Re-encode to AAC as
        # a fallback — slower but works.
        cmd_reencode = [
            pv_cache._ffmpeg_exe(),
            "-y",
            "-loglevel", "error",
            "-i", str(video_path),
            "-vn",
            "-c:a", "aac",
            "-b:a", "64k",
            "-f", "mp4",
            str(tmp),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd_reencode,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(
                f"[transcription] ffmpeg audio extract failed for {video_path.name}: "
                f"{stderr.decode(errors='replace')[:200]}"
            )
            return None
    tmp.replace(audio_path)
    return audio_path


async def transcribe(video_path: Path) -> Optional[dict]:
    """Transcribe a single video file via OpenAI Whisper.

    Returns {text, segments, model, generated_at} or None on any failure
    (no key, ffmpeg fails, file too large, API error)."""
    key = _api_key()
    if not key:
        logger.info("[transcription] skipped — OPENAI_API_KEY not set")
        return None

    audio_path = await _extract_audio(video_path)
    if not audio_path:
        return None

    size = audio_path.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        logger.warning(
            f"[transcription] audio too large for Whisper API "
            f"({size} > {MAX_UPLOAD_BYTES}); skipping"
        )
        return None

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=key)
        with audio_path.open("rb") as f:
            resp = await client.audio.transcriptions.create(
                model=WHISPER_MODEL,
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
        text = (getattr(resp, "text", None) or "").strip()
        segments_raw = getattr(resp, "segments", None) or []
        segments = [
            {
                "start": float(getattr(s, "start", 0) or 0),
                "end": float(getattr(s, "end", 0) or 0),
                "text": (getattr(s, "text", "") or "").strip(),
            }
            for s in segments_raw
        ]
        return {
            "text": text,
            "segments": segments,
            "model": WHISPER_MODEL,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.warning(f"[transcription] Whisper API failed: {e}")
        return None


async def transcribe_and_save(db, item_id: str, src_url: str) -> Optional[dict]:
    """Wait for the video to be downloaded, transcribe it, and persist the
    transcript on the row. Idempotent — re-runs are skipped if a transcript
    already exists. Designed to be called fire-and-forget from the ingest
    webhook (and lazily from the /transcript endpoint)."""
    if not configured():
        return None

    existing = await db.private_video_submissions.find_one(
        {"id": item_id}, {"_id": 0, "transcript": 1}
    )
    if (existing or {}).get("transcript"):
        return existing["transcript"]

    import private_video_cache as pv_cache
    try:
        await pv_cache.prepare(item_id, src_url)
    except Exception as e:
        logger.info(f"[transcription] download failed for {item_id}: {e}")
        return None

    video_path = pv_cache._path_orig(item_id)
    if not video_path.exists():
        logger.info(f"[transcription] no source file for {item_id}")
        return None

    transcript = await transcribe(video_path)
    if not transcript:
        return None

    try:
        await db.private_video_submissions.update_one(
            {"id": item_id}, {"$set": {"transcript": transcript}}
        )
    except Exception as e:
        logger.warning(f"[transcription] persist failed for {item_id}: {e}")
        return None
    logger.info(
        f"[transcription] saved {len(transcript.get('text') or '')} chars "
        f"for {item_id}"
    )
    return transcript
