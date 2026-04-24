"""
Google Drive + Docs integration (service-account) for private-tier doc summaries.

- Lists Google Docs / Shortcuts in a specific Drive folder.
- Fuzzy-matches filename against a student name.
- Exports the doc's plain-text content.
- Summarises via Emergent LLM (Claude Sonnet 4.5) to a ~200-word brief.

Results cached in Mongo `drive_doc_summaries` for 24 h so repeated Student
Lookups don't hit Google + LLM every time.
"""
from __future__ import annotations

import os
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
]

SUMMARY_TTL_HOURS = 24
MAX_DOC_CHARS = 12000  # Truncate input to the LLM


def _drive_service():
    sa_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    if not sa_file or not os.path.exists(sa_file):
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_FILE not configured")
    creds = service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _folder_id() -> str:
    fid = os.environ.get("GOOGLE_DRIVE_PRIVATE_TIER_FOLDER_ID")
    if not fid:
        raise RuntimeError("GOOGLE_DRIVE_PRIVATE_TIER_FOLDER_ID not configured")
    return fid


def _normalise(name: str) -> str:
    """Lowercase + strip punctuation + collapse whitespace for fuzzy compare."""
    n = re.sub(r"[^a-z0-9\s]", "", name.lower())
    return re.sub(r"\s+", " ", n).strip()


def _find_best_match(student_name: str, files: list[dict]) -> Optional[dict]:
    """
    Match strategy (first win):
    1. Filename contains the full normalised student name
    2. Filename starts with first_name + last_name tokens in any order
    3. All name tokens appear somewhere in filename

    Returns the matched file dict with optional `match_reason`.
    """
    target = _normalise(student_name)
    if not target:
        return None
    parts = target.split()

    for f in files:
        fname = _normalise(f["name"])
        if target in fname:
            return {**f, "match_reason": "exact"}

    # all tokens present (in any order)
    for f in files:
        fname = _normalise(f["name"])
        if all(p in fname for p in parts):
            return {**f, "match_reason": "tokens"}

    # fallback: last-name only if unusual (len>3)
    if len(parts) >= 2 and len(parts[-1]) > 3:
        last = parts[-1]
        for f in files:
            fname = _normalise(f["name"])
            if last in fname.split():
                return {**f, "match_reason": "lastname"}

    return None


async def _list_docs() -> list[dict]:
    """
    Returns list of {id, name, mimeType, modifiedTime, web_view_link,
    target_id (if shortcut), target_mime}.
    """
    drive = _drive_service()
    q = f"'{_folder_id()}' in parents and trashed=false"
    files: list[dict] = []
    page_token: Optional[str] = None
    while True:
        res = drive.files().list(
            q=q,
            pageSize=200,
            fields="nextPageToken, files(id,name,mimeType,modifiedTime,webViewLink,shortcutDetails)",
            pageToken=page_token,
        ).execute()
        files.extend(res.get("files", []))
        page_token = res.get("nextPageToken")
        if not page_token:
            break
    out: list[dict] = []
    for f in files:
        item = {
            "id": f["id"],
            "name": f["name"],
            "mimeType": f["mimeType"],
            "modifiedTime": f.get("modifiedTime"),
            "web_view_link": f.get("webViewLink"),
        }
        if f["mimeType"] == "application/vnd.google-apps.shortcut":
            sc = f.get("shortcutDetails") or {}
            item["target_id"] = sc.get("targetId")
            item["target_mime"] = sc.get("targetMimeType")
        out.append(item)
    return out


async def _fetch_doc_text(doc_id: str) -> str:
    """Export a Google Doc as plain text. Handles shared-drive access."""
    drive = _drive_service()
    try:
        result = drive.files().export(
            fileId=doc_id,
            mimeType="text/plain",
        ).execute()
        if isinstance(result, bytes):
            return result.decode("utf-8", errors="replace")
        return str(result)
    except HttpError as e:
        raise RuntimeError(f"Drive export failed: {e}") from e


async def _summarise(doc_name: str, doc_text: str) -> str:
    """Use Emergent LLM (Claude) to summarise the private-tier doc."""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except ImportError:
        raise RuntimeError("emergentintegrations not available")

    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        raise RuntimeError("EMERGENT_LLM_KEY not configured")

    text = doc_text[:MAX_DOC_CHARS]
    prompt = (
        "You are summarising an internal private-tier student plan document so the "
        "AYCI team can get up to speed before a call. Produce a concise "
        "briefing in plain English with short labelled sections. Avoid verbosity.\n\n"
        f"Document title: {doc_name}\n\n"
        "Document content:\n"
        f"---\n{text}\n---\n\n"
        "Return a briefing with these sections (only include a section if the doc covers it):\n"
        "- **Goals**: 1-2 lines on their interview/career goal\n"
        "- **Interview date(s)**: specific date(s) if mentioned\n"
        "- **Specialty & context**: specialty, hospital, any special context\n"
        "- **Progress so far**: calls done, mocks done, videos submitted, any notable wins/blockers\n"
        "- **Next steps**: what the team should focus on next\n"
        "- **Flags**: anything urgent or risks (e.g. confidence issues, cancelled slots, exam results)\n\n"
        "Keep the whole brief under 220 words."
    )

    session_id = f"drive-summary-{doc_name[:40]}"
    chat = LlmChat(api_key=key, session_id=session_id, system_message="Concise, factual briefing writer.")
    chat = chat.with_model("anthropic", "claude-sonnet-4-5-20250929")

    response = await chat.send_message(UserMessage(text=prompt))
    return str(response).strip()


async def summarise_student_doc(db, student_name: str, student_email: str) -> dict:
    """
    Top-level API. Returns:
    {
      "found": bool,
      "file": {id, name, web_view_link, modifiedTime} | None,
      "summary": str | None,
      "cached": bool,
      "error": str | None,
      "candidates_scanned": int,
    }
    """
    if not student_name:
        return {"found": False, "file": None, "summary": None, "cached": False, "error": "No student name", "candidates_scanned": 0}

    cache_key = (student_email or "").strip().lower() or _normalise(student_name)
    try:
        # Check cache first
        cutoff = datetime.now(timezone.utc) - timedelta(hours=SUMMARY_TTL_HOURS)
        cached = await db.drive_doc_summaries.find_one({"_id": cache_key}, {"_id": 0})
        if cached:
            cached_at = cached.get("cached_at")
            if isinstance(cached_at, datetime):
                if cached_at.tzinfo is None:
                    cached_at = cached_at.replace(tzinfo=timezone.utc)
                if cached_at > cutoff:
                    return {**cached, "cached": True}

        files = await _list_docs()
        match = _find_best_match(student_name, files)
        if not match:
            result = {
                "found": False,
                "file": None,
                "summary": None,
                "cached": False,
                "error": None,
                "candidates_scanned": len(files),
            }
            return result

        doc_id = match.get("target_id") or match["id"]
        target_mime = match.get("target_mime") or match["mimeType"]
        web_view_link = match.get("web_view_link")
        # For shortcuts, the web_view_link may be missing — build one
        if not web_view_link and match.get("target_id"):
            web_view_link = f"https://docs.google.com/document/d/{match['target_id']}/edit"

        if target_mime != "application/vnd.google-apps.document":
            # Non-doc file (PDF, sheet, etc.) — just link it
            payload = {
                "found": True,
                "file": {
                    "id": doc_id,
                    "name": match["name"],
                    "web_view_link": web_view_link,
                    "modifiedTime": match.get("modifiedTime"),
                    "mime": target_mime,
                },
                "summary": None,
                "error": "File is not a Google Doc — summary unavailable. Open the link to view.",
                "candidates_scanned": len(files),
                "cached": False,
            }
        else:
            try:
                text = await _fetch_doc_text(doc_id)
            except RuntimeError as exc:
                # Target doc isn't shared with our service account (common for
                # shortcut-style layouts). Return the shortcut link + a hint.
                msg = str(exc)
                hint = (
                    "Couldn't read the doc — looks like the target file isn't "
                    "shared with the service account. Share the doc (or its "
                    "parent folder) with "
                    "ayci-drive-reader@ayci-dashboard.iam.gserviceaccount.com "
                    "(Viewer access) to enable the summary."
                ) if "notFound" in msg or "not found" in msg.lower() or "403" in msg else msg
                return {
                    "found": True,
                    "file": {
                        "id": doc_id,
                        "name": match["name"],
                        "web_view_link": web_view_link,
                        "modifiedTime": match.get("modifiedTime"),
                        "mime": target_mime,
                    },
                    "summary": None,
                    "error": hint,
                    "candidates_scanned": len(files),
                    "cached": False,
                }
            if not text.strip():
                summary = "Document is empty."
            else:
                summary = await _summarise(match["name"], text)
            payload = {
                "found": True,
                "file": {
                    "id": doc_id,
                    "name": match["name"],
                    "web_view_link": web_view_link,
                    "modifiedTime": match.get("modifiedTime"),
                    "mime": target_mime,
                },
                "summary": summary,
                "error": None,
                "candidates_scanned": len(files),
                "cached": False,
            }

        # Store in cache
        await db.drive_doc_summaries.update_one(
            {"_id": cache_key},
            {"$set": {**payload, "cached_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        return payload
    except Exception as e:
        logger.exception(f"summarise_student_doc failed: {e}")
        # Don't cache errors — let the next attempt retry
        return {
            "found": False,
            "file": None,
            "summary": None,
            "cached": False,
            "error": str(e),
            "candidates_scanned": 0,
        }
