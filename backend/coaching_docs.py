"""
Per-student coaching docs for private-tier members.

Each Private Plus / VIP student should have one Google Doc in the shared private-tier
folder, titled "Name - Specialty - Type - Date", where coaches write call notes. The
dashboard links + AI-summarises it (google_drive.py).

Historically these were made by hand, so some are missing and others are mis-named
(the Oksana -> Megan gap). This module:
  - builds the correct title from the dashboard fields,
  - ensures every current private-tier student has a doc: adopt+rename an existing
    match, or create a fresh blank one,
  - stores the Google Doc id on the student (`coaching_doc_id`) so matching is EXACT
    (no more fuzzy-filename guessing), pinned against the Monday sync.

`ensure(dry_run=True)` is READ-ONLY (reports the plan). `dry_run=False` writes -
needs the service account to have WRITE_SCOPES + Content-manager on the shared drive.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import google_drive

logger = logging.getLogger(__name__)


def build_title(row: dict) -> str:
    """"Name - Specialty - Type - Date" from the dashboard fields, omitting any part
    we don't have yet (so a student with no interview date still gets Name - Specialty)."""
    name = (row.get("name") or "").strip()
    spec = (row.get("interview_speciality") or row.get("speciality") or "").strip()
    itype = (row.get("interview_type") or "").strip()
    date = (row.get("interview_date") or "").strip()
    segs = [s for s in [name, spec, itype, date] if s]
    return " - ".join(segs) or (name or "Coaching notes")


async def _store_doc(db, row: dict, file_id: str, url: str | None, title: str) -> None:
    pinned = sorted(set(row.get("dashboard_edited_fields") or [])
                    | {"coaching_doc_id", "coaching_doc_url", "coaching_doc_title"})
    await db.academy_members.update_one({"_id": row["_id"]}, {"$set": {
        "coaching_doc_id": file_id,
        "coaching_doc_url": url or f"https://docs.google.com/document/d/{file_id}/edit",
        "coaching_doc_title": title,
        "dashboard_edited_fields": pinned,
        "dashboard_edited_at": datetime.now(timezone.utc),
        "dashboard_edited_by": "coaching-doc-ensure",
    }})


async def ensure(db, *, dry_run: bool = True, adopt_fuzzy: bool = False,
                 status_key: str | None = None) -> dict:
    """For every current private-tier student, make sure they have a correctly-named
    coaching doc. Actions per student:
      - stored id already → rename if the title has drifted, else OK
      - no stored id, CONFIDENT filename match (exact/tokens/lastname) → adopt + rename
      - no stored id, FUZZY match → flag for review (unless adopt_fuzzy=True)
      - no match at all → create a new blank doc
    Read-only when dry_run=True.
    """
    from routes.students_db import _is_current_private_tier, _is_boss

    files = await google_drive._list_docs()  # one Drive call; matched in memory
    by_id = {}
    for f in files:
        by_id[f.get("target_id") or f["id"]] = f
        by_id[f["id"]] = f

    report: dict = {"dry_run": dry_run, "scanned": 0, "created": [], "renamed": [],
                    "adopted": [], "ok": [], "flagged": [], "errors": []}

    async for r in db.academy_members.find({}, {"columns": 0, "columns_by_id": 0}):
        if not _is_current_private_tier(r.get("tier")) or _is_boss(r) or r.get("setup_not_needed"):
            continue
        report["scanned"] += 1
        name = r.get("name") or ""
        title = build_title(r)
        stored_id = r.get("coaching_doc_id")
        try:
            if stored_id:
                cur = by_id.get(stored_id)
                cur_name = cur["name"] if cur else None
                if cur and cur_name != title:
                    if not dry_run:
                        google_drive.rename_file(stored_id, title)
                        await _store_doc(db, r, stored_id, r.get("coaching_doc_url"), title)
                    report["renamed"].append({"id": r["_id"], "name": name, "from": cur_name, "to": title})
                else:
                    report["ok"].append({"id": r["_id"], "name": name, "title": title})
                continue

            match = google_drive._find_best_match(name, files)
            if match and not match.get("needs_verification"):
                fid = match.get("target_id") or match["id"]
                if not dry_run:
                    if match["name"] != title:
                        google_drive.rename_file(fid, title)
                    await _store_doc(db, r, fid, match.get("web_view_link"), title)
                report["adopted"].append({"id": r["_id"], "name": name, "doc": match["name"],
                                          "to": title, "reason": match.get("match_reason")})
            elif match and match.get("needs_verification") and not adopt_fuzzy:
                report["flagged"].append({"id": r["_id"], "name": name, "maybe_doc": match["name"],
                                          "score": match.get("match_score"), "reason": match.get("match_reason"),
                                          "would_title": title})
            else:
                if not dry_run:
                    created = google_drive.create_blank_doc(title)
                    await _store_doc(db, r, created["id"], created["web_view_link"], title)
                    report["created"].append({"id": r["_id"], "name": name, "title": title,
                                              "doc_id": created["id"], "url": created["web_view_link"]})
                else:
                    report["created"].append({"id": r["_id"], "name": name, "title": title})
        except Exception as e:
            logger.warning(f"[coaching-doc] ensure failed for {r.get('_id')} ({name}): {e}")
            report["errors"].append({"id": r["_id"], "name": name, "error": str(e)})

    report["counts"] = {k: len(v) for k, v in report.items() if isinstance(v, list)}
    if status_key is not None:
        await db.fn_cache.update_one(
            {"_id": status_key},
            {"$set": {"state": "done", "result": report, "finished_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    logger.info(f"[coaching-doc] ensure {report['counts']} (dry_run={dry_run})")
    return report
