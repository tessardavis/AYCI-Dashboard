"""
Safety net for the `private_video_submissions` collection.

The private-tier video board is the single home of those rows (status, reply
links, replied dates). A logic bug, a bad sync, or a manual drop could empty
it - and a transient *load* failure can make it merely look empty. So we:

  1. Keep dated, lean nightly SNAPSHOTS (transcript text excluded - it's heavy
     and regenerable) we can restore from. take_snapshot() / restore_snapshot().
  2. Shout in Slack the moment the live row count COLLAPSES versus the last
     snapshot, so a real wipe is instantly distinguishable from "looks empty".

Snapshots live in the same cluster (so they survive collection-level loss /
bad syncs / logic bugs - the realistic failure modes here). They are NOT a
substitute for Atlas's own cluster backups.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from slack_dm import post_to_channel

logger = logging.getLogger(__name__)

BACKUP_COLLECTION = "private_video_backups"
KEEP_SNAPSHOTS = 14  # ~2 weeks of nightly snapshots
ALERT_CHANNEL = (os.environ.get("SLACK_FULFILLMENT_CHANNEL") or "#fulfillment-team").strip()
COLLAPSE_KEY = "private_video_collapse_alert"  # latch in app_settings so we alert once per incident


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def take_snapshot(db) -> dict:
    """Copy every row (minus the heavy transcript text) into one dated snapshot
    doc, then prune to the last KEEP_SNAPSHOTS."""
    docs = await db.private_video_submissions.find(
        {}, {"_id": 0, "transcript": 0}
    ).to_list(5000)
    by_status: dict = {}
    for d in docs:
        s = d.get("status") or "new"
        by_status[s] = by_status.get(s, 0) + 1
    snap = {
        "id": str(uuid.uuid4()),
        "taken_at": _now_iso(),
        "count": len(docs),
        "by_status": by_status,
        "docs": docs,
    }
    await db[BACKUP_COLLECTION].insert_one(snap)
    # Prune older snapshots beyond the retention window.
    stale = await db[BACKUP_COLLECTION].find(
        {}, {"_id": 1}
    ).sort("taken_at", -1).skip(KEEP_SNAPSHOTS).to_list(1000)
    if stale:
        await db[BACKUP_COLLECTION].delete_many({"_id": {"$in": [s["_id"] for s in stale]}})
    logger.info(f"[pv-backup] snapshot {snap['id']} rows={snap['count']} by_status={by_status}")
    return {"id": snap["id"], "count": snap["count"], "by_status": by_status, "taken_at": snap["taken_at"]}


async def check_collapse_and_alert(db) -> dict:
    """Alert (once per incident) if the live count collapses vs the last
    snapshot. 'Collapse' = live is 0, or under half the last snapshot's count.
    Latched in app_settings so we don't re-ping every tick; cleared (with a
    recovery note) once the count is healthy again."""
    live = await db.private_video_submissions.count_documents({})
    last = await db[BACKUP_COLLECTION].find_one(
        {}, {"_id": 0, "count": 1, "taken_at": 1}, sort=[("taken_at", -1)]
    )
    baseline = int((last or {}).get("count") or 0)
    # Only meaningful once we have a real baseline to compare against.
    collapsed = baseline > 5 and (live == 0 or live < baseline * 0.5)
    state = await db.app_settings.find_one({"id": COLLAPSE_KEY}, {"_id": 0, "active": 1})
    already = bool((state or {}).get("active"))

    if collapsed and not already:
        text = (
            ":rotating_light: *Private-Tier Videos: row count collapsed* - the "
            f"board now has *{live}* rows, down from *{baseline}* at the last "
            f"nightly snapshot ({(last or {}).get('taken_at', '?')}).\n"
            "Usually this is a load/display glitch rather than data loss - open "
            "the Private-Tier Videos page to check. If rows really are missing, "
            "an admin can restore the latest snapshot.\n"
            "_Do NOT click 'Migrate from Monday board' - it overwrites with older data._"
        )
        res = await post_to_channel(db, ALERT_CHANNEL, text)
        await db.app_settings.update_one(
            {"id": COLLAPSE_KEY},
            {"$set": {"id": COLLAPSE_KEY, "active": True, "live": live,
                      "baseline": baseline, "alerted_at": _now_iso()}},
            upsert=True,
        )
        logger.warning(f"[pv-backup] COLLAPSE alert live={live} baseline={baseline} slack_ok={res.get('ok')}")
        return {"alerted": True, "live": live, "baseline": baseline}

    if not collapsed and already:
        await db.app_settings.update_one(
            {"id": COLLAPSE_KEY}, {"$set": {"active": False, "recovered_at": _now_iso(), "live": live}}
        )
        await post_to_channel(
            db, ALERT_CHANNEL,
            f":white_check_mark: Private-Tier Videos row count is healthy again (*{live}* rows).",
        )
        logger.info(f"[pv-backup] collapse cleared live={live}")

    return {"alerted": False, "live": live, "baseline": baseline}


async def list_snapshots(db) -> list:
    """Snapshot metadata (no doc bodies), newest first."""
    out = []
    async for s in db[BACKUP_COLLECTION].find({}, {"_id": 0, "docs": 0}).sort("taken_at", -1):
        out.append(s)
    return out


async def restore_snapshot(db, snapshot_id: str | None = None) -> dict:
    """Upsert every doc from a snapshot back into the live collection (keyed by
    `id`). Restores deleted rows and rolls fields back to the snapshot state.
    Additive and safe: it never deletes rows that exist now but weren't in the
    snapshot. Defaults to the most recent snapshot."""
    from pymongo import UpdateOne

    if snapshot_id:
        snap = await db[BACKUP_COLLECTION].find_one({"id": snapshot_id})
    else:
        snap = await db[BACKUP_COLLECTION].find_one({}, sort=[("taken_at", -1)])
    if not snap:
        return {"ok": False, "error": "snapshot not found"}

    now = _now_iso()
    ops = []
    for d in snap.get("docs") or []:
        if not d.get("id"):
            continue
        doc = {k: v for k, v in d.items() if k != "_id"}
        doc["restored_at"] = now
        ops.append(UpdateOne({"id": d["id"]}, {"$set": doc}, upsert=True))
    restored = 0
    if ops:
        res = await db.private_video_submissions.bulk_write(ops, ordered=False)
        restored = (res.upserted_count or 0) + (res.modified_count or 0)
    logger.warning(f"[pv-backup] restored snapshot {snap['id']} rows={len(ops)} applied={restored}")
    return {
        "ok": True,
        "snapshot_id": snap["id"],
        "taken_at": snap["taken_at"],
        "rows_in_snapshot": len(snap.get("docs") or []),
        "restored": restored,
    }
