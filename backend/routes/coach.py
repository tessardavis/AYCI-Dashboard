"""Coach activity dashboard."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal, Optional

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
    cohort: Optional[str] = None,
    user: dict = Depends(require_board("coach_activity")),
):
    """Aggregated coaching engagement across Circle spaces + private video
    responses. Cached 30 min via SWR. `cohort` shows a past cohort (a key of
    coach_activity.COHORT_COACH_SPACES); default = the current cohort."""
    key = f"coach_activity:summary:{(cohort or 'current').strip()}"
    if refresh:
        await db["fn_cache"].delete_one({"_id": key})
    return await launches_mod._stale_while_revalidate(
        db,
        key,
        ttl_min=30,
        compute_fn=lambda: coach_act.fetch_coach_activity_summary(db, cohort),
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
    force: bool = False,
    user: dict = Depends(require_board("coach_activity")),
):
    """Run the over-allowance check + post alerts to #fulfillment-team right now.
    Useful for testing or after a manual Monday-allowance fix. `?force=true`
    re-posts every current breach, ignoring the already-alerted dedup (for a
    test)."""
    return await over_alerts.notify_over_allowance_breaches(db, force=force)



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


async def _diagnose_post_comments(post_id: int) -> dict:
    """Fetch Circle comments for one post and report how the coach-roster
    matching logic interprets each one. Shared between debug-comments
    (by post_id) and debug-comments-by-url (by Circle URL)."""
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
        # Circle returns rich_text_body as a structured dict (tiptap doc) on
        # voice-note + emoji-heavy comments — strip out the fallback text so
        # we don't try to slice a dict.
        body_text = (
            cm.get("body")
            or (cm.get("rich_text_body") or {}).get("circle_ios_fallback_text")
            or cm.get("plain_text")
            or ""
        )
        if not isinstance(body_text, str):
            body_text = str(body_text)
        interpreted.append({
            "comment_id": cm.get("id"),
            "parent_comment_id": cm.get("parent_comment_id"),
            "extracted_name": name,
            "extracted_email": email,
            "matched_coach": canon,
            "is_recognised_coach": canon is not None,
            "top_level_keys": sorted(list(cm.keys())),
            "body_preview": body_text[:120],
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
    return await _diagnose_post_comments(post_id)


@router.get("/coach-activity/debug-comments-by-url")
async def coach_activity_debug_comments_by_url(
    url: str,
    admin: dict = Depends(require_admin),
):
    """Same diagnostic as debug-comments/{post_id} but accepts a Circle post
    URL (e.g. https://ayci-academy.circle.so/c/<space>/<post-slug>). Looks
    up the numeric post_id by listing posts in the two tracked spaces and
    matching by slug, then runs the standard diagnostic."""
    import httpx
    from urllib.parse import urlparse
    import coach_activity as coach_act
    from connectors import TIMEOUT

    path = urlparse(url).path
    parts = [p for p in path.split("/") if p]
    # Expected shape: /c/<space-slug>/<post-slug>[/...]
    if len(parts) < 3 or parts[0] != "c":
        return {
            "error": "URL must look like https://<community>.circle.so/c/<space>/<post-slug>",
            "parsed_path": path,
        }
    post_slug = parts[2]

    spaces_to_search = [
        ("recorded_answer_review", coach_act.RECORDED_ANSWER_SPACE_ID),
        ("interview_support", coach_act.INTERVIEW_SUPPORT_SPACE_ID),
    ]
    found_post_id: int | None = None
    searched: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            for label, sid in spaces_to_search:
                try:
                    posts = await coach_act._circle_list_posts_in_space(c, sid)
                except httpx.HTTPStatusError as e:
                    searched.append({
                        "space": label, "space_id": sid, "post_count": 0,
                        "error": f"Circle API {e.response.status_code}: {e.response.text[:200]}",
                    })
                    continue
                except httpx.HTTPError as e:
                    searched.append({
                        "space": label, "space_id": sid, "post_count": 0,
                        "error": f"Circle API network error: {type(e).__name__}: {e}",
                    })
                    continue
                searched.append({"space": label, "space_id": sid, "post_count": len(posts)})
                for p in posts:
                    p_slug = p.get("slug")
                    p_url = p.get("url") or ""
                    if p_slug == post_slug or p_url.rstrip("/").endswith("/" + post_slug):
                        found_post_id = p.get("id")
                        break
                if found_post_id:
                    break
    except Exception as e:
        return {
            "error": f"Unexpected error while searching spaces: {type(e).__name__}: {e}",
            "post_slug": post_slug,
            "searched": searched,
        }

    if not found_post_id:
        return {
            "error": f"No post matching slug '{post_slug}' found in the tracked spaces",
            "post_slug": post_slug,
            "searched": searched,
        }

    try:
        result = await _diagnose_post_comments(found_post_id)
    except Exception as e:
        return {
            "error": f"Found post {found_post_id} but comments fetch failed: {type(e).__name__}: {e}",
            "post_slug": post_slug,
            "post_id": found_post_id,
            "searched": searched,
        }
    result["matched_post_slug"] = post_slug
    result["searched"] = searched
    return result


@router.get("/coach-activity/debug-fetch-failures/{space_id}")
async def coach_activity_debug_fetch_failures(
    space_id: int,
    admin: dict = Depends(require_admin),
):
    """List every post in a space whose /comments fetch currently fails,
    plus the underlying Circle response (status code + body preview).
    Use this to figure out why fetch_failed_count is non-zero — is it a
    pattern (old posts, certain authors, certain post types)?"""
    import httpx
    import coach_activity as coach_act
    from connectors import CIRCLE_BASE, _circle_headers, TIMEOUT

    failures: list[dict] = []
    successes = 0
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        posts = await coach_act._circle_list_posts_in_space(c, space_id)
        for p in posts:
            pid = p.get("id")
            if not pid:
                continue
            try:
                r = await c.get(
                    f"{CIRCLE_BASE}/comments",
                    headers=_circle_headers(),
                    params={"post_id": int(pid), "per_page": 1, "page": 1},
                )
                if r.status_code == 200:
                    successes += 1
                    continue
                failures.append({
                    "post_id": pid,
                    "post_name": p.get("name"),
                    "post_url": p.get("url"),
                    "post_author_email": coach_act._post_author_email(p),
                    "post_author_name": coach_act._post_author_name(p),
                    "post_created_at": p.get("created_at"),
                    "status_code": r.status_code,
                    "body_preview": r.text[:300],
                })
            except Exception as e:
                failures.append({
                    "post_id": pid,
                    "post_name": p.get("name"),
                    "post_url": p.get("url"),
                    "post_created_at": p.get("created_at"),
                    "error": f"{type(e).__name__}: {e}",
                })

    return {
        "space_id": space_id,
        "total_posts": len(posts),
        "successful_fetches": successes,
        "failure_count": len(failures),
        "failures": failures,
    }
