"""Private-Tier Video Submissions — DB-backed routes (replaces Monday board)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from db import db
from deps import require_admin, require_board
import private_videos_store as pv_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/private-videos", tags=["private-videos"])


# ------------------------------------------------------------- READ
@router.get("")
async def list_submissions(
    force: bool = False,  # legacy param, kept so existing frontend URLs work
    user: dict = Depends(require_board("private_videos")),
):
    return await pv_store.list_submissions(db, force=force)


# Status endpoint the frontend polls while we download + transcode the
# video. Lets us show a meaningful "Preparing video for Chrome…" state
# instead of a black `<video>` element that takes 30-90s to populate.
@router.get("/{item_id}/video/status")
async def video_status(
    item_id: str,
    user: dict = Depends(require_board("private_videos")),
):
    row = await db.private_video_submissions.find_one(
        {"id": item_id}, {"_id": 0, "tally_video_url": 1},
    )
    if not row:
        raise HTTPException(404, "Submission not found")
    src = row.get("tally_video_url")
    if not src:
        return {"status": "no_video"}
    import private_video_cache as pv_cache
    # Always kick off prepare — it's idempotent and ensures both download
    # AND transcode get scheduled even for files that downloaded earlier
    # but were never transcoded.
    import asyncio
    asyncio.create_task(pv_cache.prepare(item_id, src))
    status = pv_cache.get_status(item_id)
    return {"status": status}


# Proxy the Tally-hosted video through our backend so we can serve it with
# proper HTTP Range support. Tally's CDN returns 200 for Range requests
# (full body) and uses chunked transfer (no Content-Length), which makes
# iOS Safari refuse to play `<video>` inline — it requires 206 Partial
# Content + a known total size to seek/play. We cache each video to local
# disk on first access (one-time ~30s for a 400 MB file) and serve every
# subsequent read straight from disk where Range support is native.
@router.get("/{item_id}/video")
async def stream_video(
    item_id: str,
    request: Request,
    user: dict = Depends(require_board("private_videos")),
):
    row = await db.private_video_submissions.find_one(
        {"id": item_id}, {"_id": 0, "tally_video_url": 1},
    )
    if not row:
        raise HTTPException(404, "Submission not found")
    src = row.get("tally_video_url")
    if not src:
        raise HTTPException(404, "No video on this submission")

    import private_video_cache as pv_cache
    try:
        path = await pv_cache.ensure_ready(item_id, src)
    except Exception as e:
        logger.warning(f"[private-videos] cache prepare failed: {e}")
        raise HTTPException(502, "Video preparation failed")

    total = path.stat().st_size

    # Parse Range: bytes=START-END (END optional)
    range_header = request.headers.get("range") or ""
    start = 0
    end = total - 1
    is_range = False
    open_ended = False
    if range_header.startswith("bytes="):
        is_range = True
        try:
            spec = range_header.split("=", 1)[1].split(",")[0].strip()
            s, _, e = spec.partition("-")
            if s:
                start = int(s)
            if e:
                end = int(e)
            else:
                open_ended = True
                end = total - 1
            if end >= total:
                end = total - 1
            if start < 0 or start > end:
                raise HTTPException(416, "Requested range not satisfiable")
        except (ValueError, IndexError):
            raise HTTPException(416, "Invalid Range header")

    # Cap open-ended Range responses (`bytes=N-`) at 8 MB. Chrome's media
    # demuxer aborts when it receives a 206 response larger than ~50 MB
    # in a single shot — chunking the response into multiple Range
    # requests is what every CDN does. After this chunk, Chrome will
    # automatically request `bytes=N-` for the next window.
    DEFAULT_WINDOW = 8 * 1024 * 1024
    if open_ended and (end - start + 1) > DEFAULT_WINDOW:
        end = start + DEFAULT_WINDOW - 1

    bytes_to_read = end - start + 1
    # Read just the requested slice into memory. For Range requests this is
    # typically <8 MB; for an open-ended GET it's the whole file (~150 MB
    # transcoded) which is still fine on this host. Using a plain `Response`
    # (instead of StreamingResponse) avoids Transfer-Encoding: chunked on
    # 206 responses which trips up Chrome's media demuxer.
    with path.open("rb") as f:
        f.seek(start)
        body = f.read(bytes_to_read)

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(len(body)),
        "Cache-Control": "private, max-age=300",
        "Content-Disposition": "inline",
    }
    from fastapi.responses import Response
    if is_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
        return Response(content=body, status_code=206, headers=headers, media_type="video/mp4")
    return Response(content=body, status_code=200, headers=headers, media_type="video/mp4")


@router.get("/users")
async def assignable_users(
    user: dict = Depends(require_board("private_videos")),
):
    """Returns the assignee dropdown — now uses our internal team_members
    rather than Monday users. Same shape as before so the frontend works."""
    return {"users": await pv_store.get_team_users(db)}


# ------------------------------------------------------------- WRITE
class PrivateVideoPatch(BaseModel):
    status_label: Optional[str] = None
    assignee_id: Optional[str] = None  # now a team_member id
    replied: Optional[str] = None
    reply_link: Optional[str] = None
    private_chat_url: Optional[str] = None
    interview_date: Optional[str] = None


@router.patch("/{item_id}")
async def update_submission(
    item_id: str,
    patch: PrivateVideoPatch,
    user: dict = Depends(require_board("private_videos")),
):
    payload = patch.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(400, "No editable fields supplied")
    res = await pv_store.update_submission(db, item_id, payload)
    if not res.get("ok"):
        raise HTTPException(404, res.get("reason") or "Update failed")
    return res["item"]


# ------------------------------------------------------------- TALLY WEBHOOK
@router.post("/tally-webhook")
async def tally_webhook(request: Request):
    """Public webhook Tally posts to whenever a private-tier video is submitted.
    Configure in Tally: form 0Qr5py → Integrations → Webhook URL =
    https://<host>/api/private-videos/tally-webhook"""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")
    try:
        return await pv_store.ingest_tally_submission(db, payload)
    except Exception as e:
        # Never 500 — Tally would aggressively retry. Log and ack.
        logger.exception(f"[private-videos] tally webhook error: {e}")
        return {"ok": False, "error": str(e)}


# ------------------------------------------------------------- ADMIN
@router.post("/migrate-from-monday")
async def migrate_from_monday(admin: dict = Depends(require_admin)):
    """One-off migration: pull all 462 rows from Monday board 5083952249 and
    upsert into MongoDB. Idempotent — safe to re-run."""
    return await pv_store.migrate_from_monday(db)


@router.get("/stats")
async def stats(user: dict = Depends(require_board("private_videos"))):
    """Quick health check for the admin: how many rows in DB, and how many of
    those came from Monday vs Tally."""
    total = await db.private_video_submissions.count_documents({})
    from_monday = await db.private_video_submissions.count_documents(
        {"monday_item_id": {"$ne": None}}
    )
    from_tally = await db.private_video_submissions.count_documents(
        {"tally_submission_id": {"$ne": None}}
    )
    return {"total": total, "from_monday": from_monday, "from_tally": from_tally}


# -------------------------------------------- Zapier "Send to Circle" webhook
# Storage pattern matches the Slack webhooks: DB first, env var fallback.
async def _get_zapier_url() -> str:
    doc = await db.app_settings.find_one(
        {"id": "zapier_circle_reply_webhook"}, {"_id": 0, "value": 1}
    )
    db_val = (doc or {}).get("value") or ""
    return (db_val.strip() or os.environ.get("ZAPIER_CIRCLE_REPLY_WEBHOOK") or "").strip()


@router.get("/zapier-webhook")
async def get_zapier_webhook(admin: dict = Depends(require_admin)):
    url = await _get_zapier_url()
    return {
        "configured": bool(url),
        "masked": (url[:38] + "…" + url[-6:]) if url and len(url) > 50 else (url or ""),
    }


class ZapierWebhookPayload(BaseModel):
    url: str = ""


@router.post("/zapier-webhook")
async def set_zapier_webhook(
    body: ZapierWebhookPayload,
    admin: dict = Depends(require_admin),
):
    url = (body.url or "").strip()
    if url and not url.startswith("https://hooks.zapier.com/"):
        return {"ok": False, "error": "Expected a Zapier webhook URL starting with 'https://hooks.zapier.com/'"}
    await db.app_settings.update_one(
        {"id": "zapier_circle_reply_webhook"},
        {"$set": {"id": "zapier_circle_reply_webhook", "value": url}},
        upsert=True,
    )
    return {"ok": True, "configured": bool(url)}


@router.post("/{item_id}/send-to-circle")
async def send_to_circle(
    item_id: str,
    user: dict = Depends(require_board("private_videos")),
):
    """POST the voicenote URL to the configured Zapier webhook (which then
    posts a fixed message into the student's Circle Group DM). On success,
    stamp `replied_at = now` and flip status → Done."""
    row = await db.private_video_submissions.find_one({"id": item_id}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Submission not found")

    reply_url = (row.get("reply_link") or "").strip()
    if not reply_url:
        raise HTTPException(400, "Add the voicenote URL first (Reply link field)")

    zapier_url = await _get_zapier_url()
    if not zapier_url:
        raise HTTPException(
            400,
            "Zapier webhook not configured — set it in Settings → Integrations → 'Zapier Circle reply webhook'",
        )

    # Resolve assignee name for the payload
    assignee_name = None
    if row.get("assignee_team_member_id"):
        tm = await db.team_members.find_one(
            {"id": row["assignee_team_member_id"]}, {"_id": 0, "name": 1}
        )
        assignee_name = (tm or {}).get("name")

    student_name = (
        f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
        or row.get("email")
    )
    sub_num = row.get("submission_number")
    total = row.get("total_allowance")
    pulse_name = student_name
    if sub_num and total:
        pulse_name = f"{student_name} video {sub_num} of {total}"

    # Build a payload that's BOTH:
    #   - Monday-mimicking (so any pre-existing zap steps reading
    #     event.pulseId / event.pulseName / event.columnTitle keep working
    #     for migrated rows)
    #   - All native row data inline (so the zap can be rewired to read
    #     student_email / voicenote_url / etc. directly instead of
    #     re-querying Monday — needed for Tally-ingested rows where the
    #     pulseId doesn't exist on Monday).
    now_iso = datetime.now(timezone.utc).isoformat()
    payload = {
        "event": {
            "app": "ayci-dashboard",
            "type": "send_reply_via_circle",
            "triggerTime": now_iso,
            "boardId": 5083952249,
            "pulseId": row.get("monday_item_id"),  # may be null for native rows
            "pulseName": pulse_name,
            "columnId": "button_mkxmqgxc",
            "columnTitle": "Send reply (via Circle)",
            "value": {"clicks": 1, "changedAt": now_iso},
        },
        # Native fields (inline; preferred — works for both migrated + native rows)
        "submission_id": row.get("id"),
        "student_email": row.get("email"),
        "student_name": student_name,
        "first_name": row.get("first_name"),
        "last_name": row.get("last_name"),
        "voicenote_url": reply_url,
        "reply_link": reply_url,  # alias for zap convenience
        "private_chat_url": row.get("private_chat_url"),
        "submission_number": sub_num,
        "total_allowance": total,
        "question": row.get("question"),
        "tally_video_url": row.get("tally_video_url"),
        "assignee_name": assignee_name,
        "tier": row.get("tier"),
    }

    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(zapier_url, json=payload)
    except Exception as e:
        logger.warning(f"[private-videos] zapier send failed for {item_id}: {e}")
        raise HTTPException(502, f"Failed to reach Zapier: {e}") from e

    if r.status_code >= 300:
        logger.warning(f"[private-videos] zapier returned {r.status_code}: {r.text[:200]}")
        raise HTTPException(502, f"Zapier returned HTTP {r.status_code}")

    # Mark replied + Done
    update = {
        "replied_at": now_iso,
        "status": "done",
        "updated_at": now_iso,
    }
    await db.private_video_submissions.update_one(
        {"id": item_id}, {"$set": update}
    )
    fresh = await db.private_video_submissions.find_one({"id": item_id}, {"_id": 0})
    team_by_id = await pv_store._team_members_by_id(db)
    return {
        "ok": True,
        "item": pv_store._decorate(fresh, team_by_id),
        "zapier_status": r.status_code,
    }
