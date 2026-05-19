"""Coach activity dashboard."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

import coach_activity as coach_act
import coach_activity_dismissals as dismissals
import launches as launches_mod
import over_allowance_alerts as over_alerts

from db import db
from deps import require_admin, require_board

router = APIRouter(prefix="/api", tags=["coach"])


class DismissRequest(BaseModel):
    alert_type: Literal["unanswered", "rate_limited"]
    key: str = Field(..., min_length=1, max_length=300)


@router.get("/coach-activity/summary")
async def coach_activity_summary(
    refresh: bool = False,
    user: dict = Depends(require_board("coach_activity")),
):
    """Aggregated coaching engagement across Circle spaces + private video
    responses. Cached 30 min via SWR."""
    if refresh:
        await db["fn_cache"].delete_one({"_id": "coach_activity:summary"})
    return await launches_mod._stale_while_revalidate(
        db,
        "coach_activity:summary",
        ttl_min=30,
        compute_fn=lambda: coach_act.fetch_coach_activity_summary(db),
    )


@router.post("/coach-activity/dismiss")
async def coach_activity_dismiss(
    payload: DismissRequest,
    user: dict = Depends(require_board("coach_activity")),
):
    """Mark an Awaiting-coach-reply or Posting>3/week alert as 'not needed'.
    Dismissals are SHARED across the team and persist forever. The same
    dedup key also suppresses future Slack pings for rate-limited alerts."""
    res = await dismissals.dismiss(
        db,
        alert_type=payload.alert_type,
        key=payload.key,
        by_user_id=user.get("id"),
        by_name=user.get("name"),
    )
    # Bust the SWR cache so the freshly-dismissed item disappears immediately
    await db["fn_cache"].delete_one({"_id": "coach_activity:summary"})
    return res


@router.post("/coach-activity/undismiss")
async def coach_activity_undismiss(
    payload: DismissRequest,
    user: dict = Depends(require_board("coach_activity")),
):
    """Restore a previously-dismissed alert (in case it was a mistake)."""
    if not user:
        raise HTTPException(401, "auth required")
    res = await dismissals.undismiss(
        db, alert_type=payload.alert_type, key=payload.key,
    )
    await db["fn_cache"].delete_one({"_id": "coach_activity:summary"})
    return res



# -- Over-allowance bookings ------------------------------------------------
@router.get("/coach-activity/over-allowance")
async def coach_activity_over_allowance(
    refresh: bool = False,
    user: dict = Depends(require_board("coach_activity")),
):
    """List of currently over-booked students (Calendly all-time private
    calls > Monday total allowance). Cached snapshot is refreshed by the
    5-min scheduled job; set `refresh=true` to recompute immediately."""
    if refresh:
        snapshot = await over_alerts.find_over_allowance_students(db)
        await db.fn_cache.update_one(
            {"_id": over_alerts.OVER_ALLOWANCE_CACHE_KEY},
            {"$set": {"_id": over_alerts.OVER_ALLOWANCE_CACHE_KEY,
                      "value": snapshot,
                      "computed_at": snapshot["computed_at"]}},
            upsert=True,
        )
        return snapshot
    return await over_alerts.get_cached_over_allowance(db)


@router.post("/coach-activity/over-allowance/notify")
async def coach_activity_over_allowance_notify(
    user: dict = Depends(require_board("coach_activity")),
):
    """Force the over-allowance check + Slack DM to Oksana right now.
    Useful for testing or after a manual Monday-allowance fix."""
    return await over_alerts.notify_over_allowance_breaches(db)



class OverAllowanceAckRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=200)
    over_by: int = Field(..., ge=1)


@router.post("/coach-activity/over-allowance/ack")
async def coach_activity_over_allowance_ack(
    body: OverAllowanceAckRequest,
    user: dict = Depends(require_board("coach_activity")),
):
    """Acknowledge a specific (student, over_by) breach so the widget hides
    the row. Re-surfaces if the student goes further over (+1 → +2)."""
    res = await over_alerts.acknowledge_over_allowance(
        db,
        email=body.email,
        over_by=body.over_by,
        by_user_id=user.get("id"),
        by_name=user.get("name"),
    )
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "ack failed")
    return res


@router.get("/coach-activity/over-allowance/acks")
async def coach_activity_over_allowance_acks(
    user: dict = Depends(require_board("coach_activity")),
):
    """Recent over-allowance acknowledgements (newest first) — used for the
    audit-trail footer on the widget."""
    rows = await db.over_allowance_acks.find(
        {}, {"_id": 0},
    ).sort("acked_at", -1).limit(50).to_list(50)
    return {"acks": rows}


@router.get("/coach-activity/debug-comments/{post_id}")
async def coach_activity_debug_comments(
    post_id: int,
    admin: dict = Depends(require_admin),
):
    """Diagnostic: dump Circle's raw /comments response for one post and
    show how our matching logic interprets each comment. Use this to figure
    out why a post is still in 'Awaiting coach reply' when it's actually
    been replied to (typically: comment author shape that _comment_author_name
    doesn't extract, or a coach display name that the roster doesn't match)."""
    import httpx
    import coach_activity as coach_act
    from connectors import CIRCLE_BASE, _circle_headers, TIMEOUT

    raw: list[dict] = []
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        page = 1
        while page <= 20:
            r = await c.get(
                f"{CIRCLE_BASE}/comments",
                headers=_circle_headers(),
                params={"post_id": int(post_id), "per_page": 100, "page": page},
            )
            if r.status_code != 200:
                return {
                    "post_id": post_id,
                    "error": f"Circle API returned {r.status_code}",
                    "body_snippet": r.text[:500],
                }
            body = r.json()
            recs = body.get("records") or body.get("data") or []
            raw.extend(recs)
            if len(recs) < 100:
                break
            page += 1

    interpreted = []
    for cm in raw:
        name = coach_act._comment_author_name(cm)
        email = coach_act._comment_author_email(cm)
        canon = coach_act._coach_canonical(name, email)
        interpreted.append({
            "comment_id": cm.get("id"),
            "parent_comment_id": cm.get("parent_comment_id"),
            "extracted_name": name,
            "extracted_email": email,
            "matched_coach": canon,
            "is_recognised_coach": canon is not None,
            "top_level_keys": sorted(list(cm.keys())),
            "body_preview": (cm.get("body") or cm.get("rich_text_body") or "")[:120],
        })

    answered = any(row["is_recognised_coach"] for row in interpreted)
    return {
        "post_id": post_id,
        "comment_count": len(raw),
        "would_be_marked_answered": answered,
        "interpreted": interpreted,
        "raw_first": raw[0] if raw else None,
        "raw_all": raw,
    }
