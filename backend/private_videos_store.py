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


# Fields that describe the STUDENT, not the individual submission. When a
# coach edits any of these on a row we persist the value to
# `student_overrides` (keyed by email) and back-fill every other row for
# the same student, so a one-time fix sticks for past + future submissions.
STUDENT_LEVEL_FIELDS = (
    "tier",
    "total_allowance",
    "private_chat_url",
    "interview_date",
    "interview_type",
)


async def _get_student_override(db, email: str) -> dict:
    """Return the saved per-student override doc (or {} if none).
    Only the STUDENT_LEVEL_FIELDS are honoured by the ingest path."""
    if not email:
        return {}
    doc = await db.student_overrides.find_one(
        {"_id": email.strip().lower()}, {"_id": 0}
    )
    return doc or {}


async def _apply_student_override(db, email: str, values: dict) -> int:
    """Persist student-level field values for `email` and back-fill every
    existing row for the same student so the UI immediately reflects the
    correction. Returns the number of historical rows updated."""
    email = (email or "").strip().lower()
    if not email:
        return 0
    overrides = {k: v for k, v in values.items() if k in STUDENT_LEVEL_FIELDS}
    if not overrides:
        return 0
    overrides["updated_at"] = _now_iso()
    await db.student_overrides.update_one(
        {"_id": email},
        {"$set": {"_id": email, "email": email, **overrides}},
        upsert=True,
    )
    # Back-fill every existing submission for this email.
    res = await db.private_video_submissions.update_many(
        {"email": email},
        {"$set": {**overrides, "updated_at": _now_iso()}},
    )
    return int(res.modified_count or 0)


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
        "interview_type": row.get("interview_type"),
        # AI transcript availability — full text fetched via separate endpoint
        # so the list response stays small. has_transcript drives the
        # Transcript chip in the row UI.
        "has_transcript": bool((row.get("transcript") or {}).get("text")),
        # assignee — return the team_member id + name (was Monday person id + name in legacy)
        "assignee_id": row.get("assignee_team_member_id"),
        "assignee_name": (assignee or {}).get("name"),
        # tier (cached at ingest time) — informs UI styling + Zapier message
        "tier": row.get("tier"),
        # Where did this row come from? "tally" (native ingest via Tally
        # webhook), "monday" (migrated from the Monday board sync), or null
        # for legacy/manually-added rows. Used by the UI to show data-source
        # attribution chips.
        "data_source": row.get("data_source") or (
            "tally" if row.get("tally_submission_id") else
            ("monday" if row.get("monday_item_id") else None)
        ),
    }


# ------------------------------------------------------------- Read
async def list_submissions(db, *, force: bool = False) -> dict:
    """Return every submission, sorted New → Working → Done, then submitted desc.

    Side effect: pre-warm the video cache for the top active rows (status
    != "done") so by the time a coach opens an Edit modal the transcode is
    already finished. Idempotent — pv_cache.prepare bails fast if the file
    is already cached."""
    rows = await db.private_video_submissions.find(
        {}, {"_id": 0}
    ).to_list(2000)

    def _sort_key(r):
        s = r.get("status") or "new"
        sub = r.get("submitted_at") or r.get("created_at") or ""
        sub_num = int(sub[:10].replace("-", "")) if sub and len(sub) >= 10 else 0
        return (STATUS_ORDER.get(s, 99), -sub_num)

    rows.sort(key=_sort_key)

    # Fire-and-forget pre-warm for the first 10 non-Done rows that have a
    # Tally video URL. Smaller-bitrate transcodes (720p / CRF 28) cap each
    # cached file at ~35 MB, so 10 fits within the 1.2 GB /tmp budget with
    # plenty of headroom. Concurrent transcodes are throttled to 1 by the
    # cache module.
    try:
        import asyncio as _asyncio
        import private_video_cache as pv_cache
        warmed = 0
        for r in rows:
            if warmed >= 10:
                break
            if (r.get("status") or "").lower() == "done":
                continue
            tv = r.get("tally_video_url")
            if not tv or not r.get("id"):
                continue
            _asyncio.create_task(pv_cache.prepare(r["id"], tv))
            warmed += 1
    except Exception as e:
        logger.info(f"[private-videos] list-time pre-warm skipped: {e}")

    team_by_id = await _team_members_by_id(db)
    items = [_decorate(r, team_by_id) for r in rows]
    return {"items": items, "fetched_at": _now_iso(), "source": "db"}


async def boot_warm_active_videos(db, *, limit: int = 30) -> dict:
    """Schedule pv_cache.prepare for every non-done submission.

    Render's /tmp is wiped on each deploy and on idle-restart, so every
    transcode we'd previously built is gone after the next push. The
    Tally-ingest pre-warm only covers brand-new submissions; without
    this boot-warm a coach reviewing on Monday morning hits the
    "still being prepared" path on every active row.

    Fire-and-forget per row — pv_cache.prepare is idempotent, throttles
    concurrent transcodes via its own semaphore, and bails fast when
    the file is already playable. Capped so we don't queue thousands
    of transcodes after a long quiet period.
    """
    import asyncio as _asyncio
    import private_video_cache as pv_cache

    cursor = db.private_video_submissions.find(
        {"status": {"$ne": "done"}, "tally_video_url": {"$ne": None}},
        {"_id": 0, "id": 1, "tally_video_url": 1, "submitted_at": 1},
    ).sort("submitted_at", 1).limit(limit)
    scheduled = 0
    async for row in cursor:
        tv = row.get("tally_video_url")
        rid = row.get("id")
        if not (tv and rid):
            continue
        _asyncio.create_task(pv_cache.prepare(rid, tv))
        scheduled += 1
    logger.info(f"[private-videos] boot-warm scheduled {scheduled} active rows")
    return {"scheduled": scheduled}


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
    # Tier + total_allowance: editable so the team can fix rows where the
    # Monday Academy Members lookup didn't populate them (e.g. student
    # missing from Monday, or Monday tier dropdown blank). Empty string =
    # clear the override back to null.
    if "tier" in patch:
        t = (patch["tier"] or "").strip()
        allowed["tier"] = t or None
    if "total_allowance" in patch:
        allowed["total_allowance"] = _to_int(patch["total_allowance"])

    if not allowed:
        return {"ok": False, "reason": "no editable fields supplied"}
    allowed["updated_at"] = _now_iso()

    res = await db.private_video_submissions.update_one(
        {"id": submission_id}, {"$set": allowed}
    )
    if res.matched_count == 0:
        return {"ok": False, "reason": "submission not found"}

    # If the patch touched student-level fields, persist them to
    # student_overrides and back-fill every other row for this student.
    # One edit on any of the student's submissions now sticks across past
    # AND future submissions (no more re-fixing each new row).
    fresh = await db.private_video_submissions.find_one(
        {"id": submission_id}, {"_id": 0}
    )
    student_patch = {k: allowed[k] for k in STUDENT_LEVEL_FIELDS if k in allowed}
    back_filled = 0
    if student_patch and (fresh or {}).get("email"):
        back_filled = await _apply_student_override(db, fresh["email"], student_patch)
        # Re-read so the response reflects the back-fill timestamp.
        fresh = await db.private_video_submissions.find_one(
            {"id": submission_id}, {"_id": 0}
        )

    team_by_id = await _team_members_by_id(db)
    return {
        "ok": True,
        "item": _decorate(fresh, team_by_id),
        "back_filled_rows": back_filled,
    }


# ------------------------------------------------------------- Enrichment
async def _academy_lookup(db, email: str) -> dict:
    """Pull the student's row from Monday Academy Members → tier, private
    chat URL, allowance baseline, interview date + type. Returns {} on
    miss/error so ingest never fails.

    Note: `student_lookup.monday_lookup` returns `data.columns` keyed by
    column TITLE, not by column id, so we look up by the human-readable
    title from the board schema."""
    if not email:
        return {}
    try:
        import student_lookup
        result = await student_lookup.monday_lookup(email, db=db)
    except Exception as e:
        logger.warning(f"[private-videos] academy_lookup failed for {email}: {e}")
        return {}
    if not result.get("found"):
        return {}
    cols = (result.get("data") or {}).get("columns") or {}

    def _txt(title: str) -> str:
        return ((cols.get(title) or {}).get("text") or "").strip()

    tier_text = _txt("Tier").lower()
    # Prefer the authoritative scalar (set from Monday's column OR recorded by
    # private-chat-setup). Fall back to the raw Monday column text only if the
    # scalar is absent (e.g. the live-API lookup path, which doesn't surface
    # the scalar). Reading the column alone missed dashboard-recorded chats —
    # the link existed but video replies couldn't see it, so the room got
    # guessed (→ wrong DM).
    private_chat = ((result.get("data") or {}).get("private_chat_url") or "").strip() or _txt("Private Chat Link")
    interview_date = _txt("Interview Date") or None
    interview_type = _txt("Interview Type") or None

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
        "interview_date": interview_date,
        "interview_type": interview_type,
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

    # Idempotency guard — but allow resends to heal partial ingests where
    # an earlier extraction missed the question / video URL.
    existing = await db.private_video_submissions.find_one(
        {"tally_submission_id": sub_id},
        {"_id": 0, "id": 1, "question": 1, "tally_video_url": 1},
    )

    fields = data.get("fields") or []
    first = (_extract_tally_field(fields, TALLY_QID_FIRST) or "").strip()
    last = (_extract_tally_field(fields, TALLY_QID_LAST) or "").strip()
    email_raw = _extract_tally_field(fields, TALLY_QID_EMAIL)
    email = (email_raw or "").strip().lower() if isinstance(email_raw, str) else ""
    question = (_extract_tally_field(fields, TALLY_QID_QUESTION) or "").strip()

    # Tally regenerates field keys when the form is edited, so key matching
    # alone breaks silently. Fall back to label/type matching for the visible
    # inputs (question textarea + video file upload).
    if not question:
        for f in fields:
            label = (f.get("label") or "").strip().lower()
            ftype = (f.get("type") or "").upper()
            value = f.get("value")
            if (
                "question" in label
                and ftype in ("TEXTAREA", "INPUT_TEXT")
                and isinstance(value, str)
                and value.strip()
            ):
                question = value.strip()
                break

    # Hidden field fallback. The form pre-fills `name`, `lastname`, `email`
    # via URL params, but Tally has shipped this two different ways:
    #   1) Legacy: one field at TALLY_QID_HIDDEN whose value is a dict
    #   2) Current: three separate fields whose `label` is "name" /
    #      "lastname" / "email" (each with its own auto-generated key)
    # Match by label (case-insensitive) so we're robust to either shape.
    if not (first and last and email):
        by_label = {
            ((f.get("label") or "").strip().lower()): f.get("value") for f in fields
        }
        def _str(v):
            return v.strip() if isinstance(v, str) else ""
        first = first or _str(by_label.get("name"))
        last = last or _str(by_label.get("lastname"))
        email = email or _str(by_label.get("email")).lower()

        # Legacy dict-shaped hidden field
        if not (first and last and email):
            hidden = _extract_tally_field(fields, TALLY_QID_HIDDEN)
            if isinstance(hidden, dict):
                first = first or (hidden.get("name") or "").strip()
                last = last or (hidden.get("lastname") or "").strip()
                email = email or (hidden.get("email") or "").strip().lower()

    if not email:
        # Without an email we can't match the student — bail.
        # Log the field keys/labels so we can diagnose any future shape changes.
        try:
            field_summary = [
                {"key": f.get("key"), "label": f.get("label"), "type": f.get("type")}
                for f in fields
            ]
            logger.warning(
                f"[private-videos] tally submission {sub_id} ignored: no email. "
                f"Fields received: {field_summary}"
            )
        except Exception:
            pass
        return {"ignored": True, "reason": "no email"}

    # Video upload: Tally returns a list of files. Match by key, then fall
    # back to the first FILE_UPLOAD-typed field with a non-empty value list.
    video_value = _extract_tally_field(fields, TALLY_QID_VIDEO)
    if not (isinstance(video_value, list) and video_value):
        video_value = None
        for f in fields:
            if (f.get("type") or "").upper() == "FILE_UPLOAD":
                v = f.get("value")
                if isinstance(v, list) and v:
                    video_value = v
                    break
    video_url = None
    if isinstance(video_value, list) and video_value:
        video_url = (video_value[0] or {}).get("url")

    submitted_at = (
        data.get("createdAt")
        or payload.get("createdAt")
        or _now_iso()
    )

    # Resend-heal path: row already exists for this submissionId. Patch only
    # the fields the prior ingest left empty (typically question / video URL
    # when Tally field-key shape changed) and exit. Never overwrites coach
    # edits — they touch status/assignee/reply, not the source fields.
    if existing:
        patch: dict = {}
        if not (existing.get("question") or "").strip() and question:
            patch["question"] = question
        if not existing.get("tally_video_url") and video_url:
            patch["tally_video_url"] = video_url
        if patch:
            patch["updated_at"] = _now_iso()
            await db.private_video_submissions.update_one(
                {"id": existing["id"]}, {"$set": patch}
            )
            # If we just learned the video URL, kick off the cache + transcript
            # pipelines that the original ingest skipped.
            if "tally_video_url" in patch:
                try:
                    import asyncio as _asyncio
                    import private_video_cache as pv_cache
                    _asyncio.create_task(pv_cache.prepare(existing["id"], video_url))
                except Exception as e:
                    logger.info(f"[private-videos] pre-warm skipped on heal: {e}")
                try:
                    import asyncio as _asyncio
                    import transcription
                    _asyncio.create_task(
                        transcription.transcribe_and_save(db, existing["id"], video_url)
                    )
                except Exception as e:
                    logger.info(f"[private-videos] transcription skipped on heal: {e}")
            return {"ok": True, "id": existing["id"], "healed": list(patch.keys())}
        return {"ignored": True, "reason": "already ingested", "id": existing["id"]}

    # Submission number = N+1 where N is prior submissions for this email
    prior_count = await db.private_video_submissions.count_documents({"email": email})

    # Enrich from Academy Members (tier + allowance + Circle DM URL) then
    # apply any per-student overrides the team has saved via the Edit modal
    # (student_overrides collection). Overrides win — that's the whole
    # point: a coach who corrected Maha's tier/allowance/DM URL once
    # shouldn't have to redo it on every new submission.
    academy = await _academy_lookup(db, email)
    override = await _get_student_override(db, email)

    def _pick(key):
        if key in override and override[key] not in (None, ""):
            return override[key]
        return academy.get(key)

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
        "total_allowance": _pick("total_allowance"),
        "submission_number": prior_count + 1,
        "status": "new",
        "assignee_team_member_id": None,
        "replied_at": None,
        "reply_link": None,
        "private_chat_url": _pick("private_chat_url"),
        "interview_date": _pick("interview_date"),
        "interview_type": _pick("interview_type"),
        "tier": _pick("tier"),
        "data_source": "tally",
        "created_at": now,
        "updated_at": now,
    }
    await db.private_video_submissions.insert_one(row)
    logger.info(
        f"[private-videos] ingested Tally submission for {email} "
        f"(#{prior_count + 1}, tier={academy.get('tier')})"
    )

    # Pre-warm the video cache so the first coach to open this row gets
    # instant playback instead of waiting 10-30s for the HEVC → H.264
    # transcode. Fire-and-forget — never blocks the webhook response.
    # Also schedule transcription (OpenAI Whisper) in parallel so the
    # transcript is ready alongside the playable video.
    if video_url:
        try:
            import asyncio as _asyncio
            import private_video_cache as pv_cache
            _asyncio.create_task(pv_cache.prepare(row["id"], video_url))
        except Exception as e:
            logger.info(f"[private-videos] pre-warm skipped: {e}")
        try:
            import asyncio as _asyncio
            import transcription
            _asyncio.create_task(
                transcription.transcribe_and_save(db, row["id"], video_url)
            )
        except Exception as e:
            logger.info(f"[private-videos] transcription kickoff skipped: {e}")

    # If this student's interview is imminent (today/tomorrow), ping
    # #private-tiers so the video gets reviewed in time. Fire-and-forget.
    try:
        import asyncio as _asyncio
        import private_video_alerts as pva
        _asyncio.create_task(pva.notify_if_interview_imminent(db, row))
    except Exception as e:
        logger.info(f"[private-videos] imminent-interview alert skipped: {e}")

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
            row["data_source"] = "monday"
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
