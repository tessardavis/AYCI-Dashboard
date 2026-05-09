"""
Private-Tier Video Submissions — DB-backed (replaces Monday board 5083952249).

Sources:
  - Migration: one-off pull from Monday board 5083952249 → migrate_from_monday()
  - Live: Tally webhook for form 0Qr5py → ingest_tally_submission()

Schema of `private_video_submissions` collection:
    {
      id: uuid4 (our PK)
      monday_item_id: str | null  # only on migrated rows, for traceability
      tally_submission_id: str | null  # webhook idempotency key
      first_name, last_name, email (lowercased)
      submitted_at: ISO datetime
      question: str
      tally_video_url: str | null
      total_allowance: int | null   # looked up from Monday Academy Members
      submission_number: int | null # = (count of prior rows for this email) + 1
      status: "new" | "working" | "done" | "update_name"
      assignee_team_member_id: str | null  # our team_members collection PK
      replied_at: ISO datetime | null
      reply_link: str | null  # voicenote URL
      private_chat_url: str | null  # Circle DM URL (from Monday Academy Members)
      interview_date: ISO date | null
      created_at, updated_at
    }
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

STATUS_ORDER = {"new": 0, "working": 1, "done": 2, "update_name": 3}

# Tally form 0Qr5py question IDs (verified live 2026-05-07)
TALLY_FORM_ID = "0Qr5py"
TALLY_QID_FIRST = "JzG2rX"
TALLY_QID_LAST = "gGg5VJ"
TALLY_QID_EMAIL = "yYglbd"
TALLY_QID_QUESTION = "pO1ObE"
TALLY_QID_VIDEO = "X09e7z"
TALLY_QID_HIDDEN = "1VxoPQ"  # contains hidden name/lastname/email URL params

# Monday Private Plus / VIP label → video allowance baseline
TIER_VIDEO_ALLOWANCE = {
    "vip": 30,
    "private plus": 15,
    "academy private plus": 15,
    "platinum": 30,
    "boost & go": 5,
    "upgrade vip": 30,
    "upgrade private plus": 15,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_status(label: Optional[str]) -> str:
    if not label:
        return "new"
    t = str(label).lower().strip()
    if t == "new":
        return "new"
    if t in ("working on it", "working"):
        return "working"
    if t == "done":
        return "done"
    if t in ("update name", "update"):
        return "update_name"
    return "new"


def _status_label(key: str) -> str:
    return {
        "new": "New",
        "working": "Working on it",
        "done": "Done",
        "update_name": "Update name",
    }.get(key, "New")


def _to_int(v) -> Optional[int]:
    if v in (None, ""):
        return None
    try:
        return int(float(str(v).strip()))
    except Exception:
        return None


# --------------------------------------------------- Decorators (legacy shape)
async def _team_members_by_id(db) -> dict:
    """{team_member_id: {id, name, role_title}} — used to decorate assignee."""
    out = {}
    async for m in db.team_members.find({}, {"_id": 0, "id": 1, "name": 1, "role_title": 1}):
        out[m["id"]] = m
    return out


def _decorate(row: dict, team_by_id: dict) -> dict:
    """Return a row in the legacy Monday-shaped format the frontend expects."""
    assignee = team_by_id.get(row.get("assignee_team_member_id") or "")
    return {
        # primary
        "id": row.get("id"),
        "monday_item_id": row.get("monday_item_id"),
        "tally_submission_id": row.get("tally_submission_id"),
        # student
        "first_name": row.get("first_name"),
        "last_name": row.get("last_name"),
        "name": (
            f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
            or row.get("email")
            or "—"
        ),
        "email": row.get("email"),
        # submission
        "submitted": row.get("submitted_at"),
        "created_at": row.get("created_at"),
        "question": row.get("question"),
        # video / reply links — legacy nested shape
        "tally_video": {
            "label": "Watch on Tally",
            "url": row.get("tally_video_url"),
        } if row.get("tally_video_url") else {"label": None, "url": None},
        "video": {"label": None, "url": None},  # legacy field, kept for compat
        "reply_link": {
            "label": "Voicenote reply",
            "url": row.get("reply_link"),
        } if row.get("reply_link") else {"label": None, "url": None},
        # numeric
        "total_allowance": (
            str(row.get("total_allowance")) if row.get("total_allowance") is not None else None
        ),
        "submission_number": (
            str(row.get("submission_number")) if row.get("submission_number") is not None else None
        ),
        # state
        "status": _status_label(row.get("status") or "new"),
        "status_index": STATUS_ORDER.get(row.get("status") or "new", 0),
        "replied": row.get("replied_at"),
        "private_chat": row.get("private_chat_url"),
        "interview_date": row.get("interview_date"),
        # assignee — return the team_member id + name (was Monday person id + name in legacy)
        "assignee_id": row.get("assignee_team_member_id"),
        "assignee_name": (assignee or {}).get("name"),
    }


# ------------------------------------------------------------- Read
async def list_submissions(db, *, force: bool = False) -> dict:
    """Return every submission, sorted New → Working → Done, then submitted desc."""
    rows = await db.private_video_submissions.find(
        {}, {"_id": 0}
    ).to_list(2000)

    def _sort_key(r):
        s = r.get("status") or "new"
        sub = r.get("submitted_at") or r.get("created_at") or ""
        sub_num = int(sub[:10].replace("-", "")) if sub and len(sub) >= 10 else 0
        return (STATUS_ORDER.get(s, 99), -sub_num)

    rows.sort(key=_sort_key)
    team_by_id = await _team_members_by_id(db)
    items = [_decorate(r, team_by_id) for r in rows]
    return {"items": items, "fetched_at": _now_iso(), "source": "db"}


async def get_team_users(db) -> list[dict]:
    """Assignee dropdown — uses our internal team_members (not Monday users)."""
    out = []
    async for m in db.team_members.find(
        {}, {"_id": 0, "id": 1, "name": 1, "role_title": 1}
    ).sort("name", 1):
        out.append({"id": m["id"], "name": m["name"], "role_title": m.get("role_title")})
    return out


# ------------------------------------------------------------- Write
async def update_submission(db, submission_id: str, patch: dict) -> dict:
    """PATCH allowed columns. Mirrors the legacy Monday shape so the existing
    frontend can keep sending the same payload."""
    allowed: dict = {}

    # Frontend sends `status_label` ("Done"/"New"/...). Convert to internal key.
    if "status_label" in patch and patch["status_label"] is not None:
        allowed["status"] = _norm_status(patch["status_label"])
    elif "status" in patch and patch["status"] is not None:
        allowed["status"] = _norm_status(patch["status"])

    # Assignee: frontend sends `assignee_id` (now a team_member id, not Monday)
    if "assignee_id" in patch:
        allowed["assignee_team_member_id"] = patch["assignee_id"] or None

    # Replied date: frontend sends `replied` as YYYY-MM-DD or empty
    if "replied" in patch:
        allowed["replied_at"] = patch["replied"] or None

    # Reply link: voicenote URL
    if "reply_link" in patch:
        url = (patch["reply_link"] or "").strip()
        allowed["reply_link"] = url or None

    # Optional admin overrides
    if "private_chat_url" in patch:
        allowed["private_chat_url"] = (patch["private_chat_url"] or "").strip() or None
    if "interview_date" in patch:
        allowed["interview_date"] = patch["interview_date"] or None

    if not allowed:
        return {"ok": False, "reason": "no editable fields supplied"}
    allowed["updated_at"] = _now_iso()

    res = await db.private_video_submissions.update_one(
        {"id": submission_id}, {"$set": allowed}
    )
    if res.matched_count == 0:
        return {"ok": False, "reason": "submission not found"}

    fresh = await db.private_video_submissions.find_one(
        {"id": submission_id}, {"_id": 0}
    )
    team_by_id = await _team_members_by_id(db)
    return {"ok": True, "item": _decorate(fresh, team_by_id)}


# ------------------------------------------------------------- Enrichment
async def _academy_lookup(db, email: str) -> dict:
    """Pull the student's row from Monday Academy Members → tier, private chat
    URL, allowance baseline. Returns {} on miss/error so ingest never fails."""
    if not email:
        return {}
    try:
        import student_lookup
        result = await student_lookup.monday_lookup(email)
    except Exception as e:
        logger.warning(f"[private-videos] academy_lookup failed for {email}: {e}")
        return {}
    if not result.get("found"):
        return {}
    cols = (result.get("data") or {}).get("columns") or {}
    # Tier: dropdown_mkqxgqbq
    tier_text = ""
    for col_id, c in cols.items():
        if col_id == "dropdown_mkqxgqbq":
            tier_text = (c.get("text") or "").strip().lower()
            break
    # Private chat URL: text_mky9xzew
    private_chat = ""
    for col_id, c in cols.items():
        if col_id == "text_mky9xzew":
            private_chat = (c.get("text") or "").strip()
            break
    # Allowances dict already computed by lookup
    allowances = (result.get("data") or {}).get("allowances") or {}
    video_allowance = ((allowances.get("videos") or {}).get("allowance")) or None
    if not video_allowance:
        # Fallback: tier → baseline allowance
        video_allowance = TIER_VIDEO_ALLOWANCE.get(tier_text)
    return {
        "tier": tier_text or None,
        "private_chat_url": private_chat or None,
        "total_allowance": video_allowance,
    }


# ------------------------------------------------------------- Tally webhook
def _extract_tally_field(fields: list[dict], qid: str):
    """Tally webhook payload is `data.fields = [{key, label, type, value}, ...]`.
    Return the `value` for the given question id (key)."""
    for f in fields or []:
        if f.get("key") == qid:
            return f.get("value")
    return None


async def ingest_tally_submission(db, payload: dict) -> dict:
    """Process a Tally webhook event. Idempotent on submissionId.

    Tally webhook envelope (per Tally docs):
        {
          "eventId": "...",
          "eventType": "FORM_RESPONSE",
          "createdAt": "2026-05-07T12:26:06Z",
          "data": {
             "responseId": "...",
             "submissionId": "...",
             "respondentId": "...",
             "formId": "0Qr5py",
             "formName": "...",
             "createdAt": "...",
             "fields": [...]
          }
        }
    """
    data = payload.get("data") or {}
    form_id = data.get("formId") or payload.get("formId")
    if form_id != TALLY_FORM_ID:
        return {"ignored": True, "reason": f"form {form_id} not handled"}

    sub_id = (
        data.get("submissionId") or data.get("responseId") or payload.get("eventId")
    )
    if not sub_id:
        return {"ignored": True, "reason": "no submissionId"}

    # Idempotency guard
    existing = await db.private_video_submissions.find_one(
        {"tally_submission_id": sub_id}, {"_id": 0, "id": 1}
    )
    if existing:
        return {"ignored": True, "reason": "already ingested", "id": existing["id"]}

    fields = data.get("fields") or []
    first = (_extract_tally_field(fields, TALLY_QID_FIRST) or "").strip()
    last = (_extract_tally_field(fields, TALLY_QID_LAST) or "").strip()
    email = ((_extract_tally_field(fields, TALLY_QID_EMAIL) or "")).strip().lower()
    question = (_extract_tally_field(fields, TALLY_QID_QUESTION) or "").strip()

    # Hidden field may carry the canonical first/last/email if the form was
    # pre-filled via URL params. Only use it when the visible inputs are blank.
    if not (first and last and email):
        hidden = _extract_tally_field(fields, TALLY_QID_HIDDEN)
        if isinstance(hidden, dict):
            first = first or (hidden.get("name") or "").strip()
            last = last or (hidden.get("lastname") or "").strip()
            email = email or (hidden.get("email") or "").strip().lower()

    if not email:
        # Without an email we can't match the student — bail.
        return {"ignored": True, "reason": "no email"}

    # Video upload: Tally returns a list of files
    video_value = _extract_tally_field(fields, TALLY_QID_VIDEO)
    video_url = None
    if isinstance(video_value, list) and video_value:
        video_url = (video_value[0] or {}).get("url")

    submitted_at = (
        data.get("createdAt")
        or payload.get("createdAt")
        or _now_iso()
    )

    # Submission number = N+1 where N is prior submissions for this email
    prior_count = await db.private_video_submissions.count_documents({"email": email})

    # Enrich from Academy Members (tier + allowance + Circle DM URL)
    academy = await _academy_lookup(db, email)

    now = _now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "monday_item_id": None,
        "tally_submission_id": sub_id,
        "first_name": first,
        "last_name": last,
        "email": email,
        "submitted_at": submitted_at,
        "question": question,
        "tally_video_url": video_url,
        "total_allowance": academy.get("total_allowance"),
        "submission_number": prior_count + 1,
        "status": "new",
        "assignee_team_member_id": None,
        "replied_at": None,
        "reply_link": None,
        "private_chat_url": academy.get("private_chat_url"),
        "interview_date": None,
        "tier": academy.get("tier"),
        "created_at": now,
        "updated_at": now,
    }
    await db.private_video_submissions.insert_one(row)
    logger.info(
        f"[private-videos] ingested Tally submission for {email} "
        f"(#{prior_count + 1}, tier={academy.get('tier')})"
    )
    return {"ok": True, "id": row["id"]}


# ------------------------------------------------------------- Migration
async def sync_from_monday(db, *, preserve_team_edits: bool = False) -> dict:
    """Periodic sync: pull every row from Monday board 5083952249 and upsert
    into our DB. Idempotent.

    `preserve_team_edits=False` (default) — full mirror. Status, assignee,
    replied_at, reply_link from Monday all overwrite our row. This is what
    you want while Monday is the source of truth (the team replies there).

    `preserve_team_edits=True` — only Tally-source fields get refreshed
    (name, email, video URL, question). Status / assignee / reply stays as
    we have it. Use this once the team transitions to replying from THIS
    dashboard so a stray sync doesn't undo their work.
    """
    import private_videos as monday_pv
    monday_data = await monday_pv.list_submissions(db, force=True)
    items = monday_data.get("items") or []
    created = 0
    updated = 0
    now = _now_iso()
    for it in items:
        monday_id = str(it.get("id"))
        tally_url = (it.get("tally_video") or {}).get("url") or (it.get("video") or {}).get("url")
        reply_url = (it.get("reply_link") or {}).get("url")
        # Tally-source fields — always safe to overwrite from Monday
        tally_fields = {
            "first_name": (it.get("first_name") or "").strip(),
            "last_name": (it.get("last_name") or "").strip(),
            "email": (it.get("email") or "").strip().lower(),
            "submitted_at": it.get("submitted") or it.get("created_at"),
            "question": (it.get("question") or "").strip(),
            "tally_video_url": tally_url,
            "total_allowance": _to_int(it.get("total_allowance")),
            "submission_number": _to_int(it.get("submission_number")),
            "interview_date": it.get("interview_date"),
            "updated_at": now,
        }
        # Team-edit fields — only set on insert (or when preserve=False)
        team_fields = {
            "status": _norm_status(it.get("status")),
            "assignee_team_member_id": None,
            "replied_at": it.get("replied"),
            "reply_link": reply_url,
            "private_chat_url": it.get("private_chat"),
        }
        existing = await db.private_video_submissions.find_one(
            {"monday_item_id": monday_id}, {"_id": 0, "id": 1}
        )
        if existing:
            update_doc = dict(tally_fields)
            if not preserve_team_edits:
                update_doc.update(team_fields)
            await db.private_video_submissions.update_one(
                {"monday_item_id": monday_id}, {"$set": update_doc}
            )
            updated += 1
        else:
            row = {**tally_fields, **team_fields}
            row["id"] = str(uuid.uuid4())
            row["monday_item_id"] = monday_id
            row["tally_submission_id"] = None
            row["created_at"] = now
            await db.private_video_submissions.insert_one(row)
            created += 1
    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "total_in_monday": len(items),
        "preserve_team_edits": preserve_team_edits,
        "ran_at": now,
    }


async def migrate_from_monday(db) -> dict:
    """Original one-off full mirror. Kept for backwards compat."""
    return await sync_from_monday(db, preserve_team_edits=False)
