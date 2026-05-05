"""
Attachment storage for Support Tickets.

Files arriving via Gmail / Wati / Tally are downloaded and stored in MongoDB
GridFS, then referenced on the ticket as:

  ticket.attachments = [
    {id, filename, mime_type, size, gridfs_id, source, created_at}
  ]

Frontend renders image attachments inline (via the thumb endpoint) and
shows a download button for everything else.
"""
from __future__ import annotations

import logging
import mimetypes
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

logger = logging.getLogger(__name__)

MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
GRIDFS_BUCKET_NAME = "ticket_attachments"

# MIME types that are safe to render inline as <img>
INLINE_IMAGE_MIMES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/heic",
}


def _bucket(db) -> AsyncIOMotorGridFSBucket:
    return AsyncIOMotorGridFSBucket(db, bucket_name=GRIDFS_BUCKET_NAME)


def _safe_filename(name: str) -> str:
    name = (name or "").strip().replace("/", "_").replace("\\", "_")
    if not name:
        name = "attachment"
    return name[:200]  # cap


def _guess_mime(filename: str, given: Optional[str]) -> str:
    if given and "/" in given:
        return given
    guess, _ = mimetypes.guess_type(filename or "")
    return guess or "application/octet-stream"


async def store_bytes(
    db, *, data: bytes, filename: str, mime_type: Optional[str], source: str,
) -> Optional[dict]:
    """Persist a file to GridFS. Returns the attachment metadata dict (the
    shape that goes into `ticket.attachments`). Skips files exceeding
    MAX_BYTES (logged + None returned)."""
    if not data:
        return None
    size = len(data)
    if size > MAX_BYTES:
        logger.info(
            f"[attachments] skip {filename} ({size} > {MAX_BYTES}) from {source}",
        )
        return None
    fname = _safe_filename(filename)
    mt = _guess_mime(fname, mime_type)
    bucket = _bucket(db)
    grid_id = await bucket.upload_from_stream(
        fname,
        data,
        metadata={
            "content_type": mt,
            "source": source,
            "uploaded_at": datetime.now(timezone.utc),
        },
    )
    return {
        "id": str(uuid.uuid4()),
        "gridfs_id": str(grid_id),
        "filename": fname,
        "mime_type": mt,
        "size": size,
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_image": mt in INLINE_IMAGE_MIMES,
    }


async def store_from_url(
    db, *, url: str, filename: str, mime_type: Optional[str], source: str,
    headers: Optional[dict] = None,
) -> Optional[dict]:
    """Download from a URL, then store. Honours MAX_BYTES with streaming."""
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as c:
            async with c.stream("GET", url, headers=headers or {}) as r:
                if r.status_code >= 300:
                    logger.warning(
                        f"[attachments] {url} returned {r.status_code}",
                    )
                    return None
                # Honour Content-Length when present
                cl = r.headers.get("content-length")
                if cl and cl.isdigit() and int(cl) > MAX_BYTES:
                    logger.info(
                        f"[attachments] skip {filename} CL={cl} > {MAX_BYTES}",
                    )
                    return None
                # Use server-provided MIME if we don't have one
                ctype = mime_type or r.headers.get("content-type", "").split(";")[0].strip() or None
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > MAX_BYTES:
                        logger.info(
                            f"[attachments] skip {filename} streamed > {MAX_BYTES}",
                        )
                        return None
                return await store_bytes(
                    db, data=bytes(buf), filename=filename,
                    mime_type=ctype, source=source,
                )
    except Exception as e:
        logger.warning(f"[attachments] {url} fetch failed: {e}")
        return None


async def open_download_stream(db, gridfs_id: str):
    """Return an async stream for downloading. Caller must close it."""
    from bson import ObjectId
    return await _bucket(db).open_download_stream(ObjectId(gridfs_id))


async def delete_for_ticket(db, ticket: dict) -> int:
    """Garbage-collect GridFS files when a ticket is deleted."""
    from bson import ObjectId
    n = 0
    for att in ticket.get("attachments") or []:
        gid = att.get("gridfs_id")
        if not gid:
            continue
        try:
            await _bucket(db).delete(ObjectId(gid))
            n += 1
        except Exception:
            pass
    return n
