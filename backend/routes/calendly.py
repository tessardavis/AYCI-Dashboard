"""Inbound Calendly webhook + one-time admin registration.

Replaces the Zapier "Bonus Call Booked (Anoop's calendar)" zap - the action
logic lives in calendly_webhook.py. Calendly POSTs every org booking here; we
verify the signature, then act only on AYCI Bonus Call bookings.

Go-live (admin, once): POST /api/admin/calendly/register-webhook to create the
Calendly subscription and store its signing key. Inspect/clean up existing
subscriptions via GET /api/admin/calendly/webhooks.
"""
import asyncio
import logging
import os
import re
import secrets
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel

import calendly_webhook
import connectors
import launches as launches_mod
import slack_dm
from db import db
from deps import require_admin, require_board, get_current_user

router = APIRouter(prefix="/api", tags=["calendly"])
logger = logging.getLogger(__name__)

_DEFAULT_CALLBACK = "https://ayci-dashboard.onrender.com/api/calendly/webhook"


@router.post("/calendly/webhook")
async def calendly_webhook_receiver(request: Request):
    """Receive a signed Calendly event. Always returns 200 once the signature
    is valid - a handler error is logged and swallowed so Calendly doesn't
    retry-storm on a bug we've already recorded."""
    raw = await request.body()
    sig = request.headers.get("Calendly-Webhook-Signature", "")
    key = await calendly_webhook._get_signing_key(db)
    if not calendly_webhook.verify_signature(raw, sig, key):
        raise HTTPException(401, "invalid Calendly signature")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "invalid JSON")

    event = body.get("event")
    payload = body.get("payload") or {}
    try:
        if event == "invitee.created":
            result = await calendly_webhook.handle_invitee_created(db, payload)
        elif event == "invitee.canceled":
            result = await calendly_webhook.handle_invitee_canceled(db, payload)
        else:
            return {"ok": True, "skipped": event}
        return {"ok": True, "result": result}
    except Exception as e:
        logger.exception("[calendly] handler error")
        return {"ok": False, "error": str(e)[:200]}


@router.post("/admin/calendly/register-webhook")
async def register_calendly_webhook(admin: dict = Depends(require_admin)):
    """Create the org-scoped Calendly webhook subscription that feeds
    /api/calendly/webhook (invitee.created + invitee.canceled), and store its
    signing key. Re-running is safe: any existing subscription pointing at our
    callback is deleted first, so "Re-connect" works without Calendly's
    duplicate-(url, scope) error."""
    if not os.environ.get("CALENDLY_TOKEN"):
        raise HTTPException(400, "CALENDLY_TOKEN not set")
    callback = os.environ.get("CALENDLY_WEBHOOK_URL") or _DEFAULT_CALLBACK
    signing_key = secrets.token_hex(32)

    async with httpx.AsyncClient(timeout=30) as c:
        me = await c.get(f"{connectors.CALENDLY_BASE}/users/me",
                         headers=connectors._calendly_headers())
        me.raise_for_status()
        org = (me.json().get("resource") or {}).get("current_organization")
        if not org:
            raise HTTPException(400, "could not resolve Calendly organization")

        # Delete any prior subscription for this callback (idempotent re-connect).
        existing = await c.get(f"{connectors.CALENDLY_BASE}/webhook_subscriptions",
                               headers=connectors._calendly_headers(),
                               params={"organization": org, "scope": "organization"})
        for s in (existing.json().get("collection") or []) if existing.status_code < 300 else []:
            if s.get("callback_url") == callback and s.get("uri"):
                await c.delete(s["uri"], headers=connectors._calendly_headers())

        sub = await c.post(
            f"{connectors.CALENDLY_BASE}/webhook_subscriptions",
            headers={**connectors._calendly_headers(), "Content-Type": "application/json"},
            json={
                "url": callback,
                "events": ["invitee.created", "invitee.canceled"],
                "organization": org,
                "scope": "organization",
                "signing_key": signing_key,
            },
        )
    if sub.status_code >= 300:
        raise HTTPException(sub.status_code, f"Calendly rejected: {sub.text[:300]}")

    resource = sub.json().get("resource", {})
    await db.app_settings.update_one(
        {"id": "calendly_webhook"},
        {"$set": {"id": "calendly_webhook", "signing_key": signing_key,
                  "callback": callback, "subscription_uri": resource.get("uri")}},
        upsert=True,
    )
    logger.info(f"[calendly] webhook registered: {resource.get('uri')} → {callback}")
    return {"ok": True, "callback": callback, "subscription": resource}


class MarkEligibleBody(BaseModel):
    email: str


@router.post("/bonus-call/mark-eligible")
async def mark_bonus_eligible(body: MarkEligibleBody,
                              user: dict = Depends(require_board("students"))):
    """Mark a student eligible for a bonus call: apply the current cohort's
    'Ad Hoc Bonus Call' Kit tag (which triggers Kit's booking-link email).
    The tag is resolved newest-first, so it tracks the cohort automatically."""
    email = (body.email or "").strip().lower()
    if not email:
        raise HTTPException(400, "email required")
    tag_ids = await connectors._resolve_ayci_cohort_tags(calendly_webhook.AD_HOC_TAG_SUFFIX, exclude_future=True)
    if not tag_ids:
        raise HTTPException(
            400, "No 'Ad Hoc Bonus Call' tag found for the current cohort in Kit - create it first"
        )
    try:
        await connectors.convertkit_add_tag_to_subscriber(email, tag_ids[0])
    except Exception as e:
        raise HTTPException(502, f"Kit tagging failed: {str(e)[:150]}")
    logger.info(f"[bonus-call] marked eligible (ad-hoc): {email} tag={tag_ids[0]}")
    return {"ok": True, "email": email, "tag_id": tag_ids[0],
            "via": calendly_webhook.AD_HOC_TAG_SUFFIX}


async def _compute_bonus_summary() -> dict:
    """End-of-cohort snapshot for the RUNNING cohort:
      - eligible: unique subscribers across this cohort's eligibility Kit tags
      - booked:   subscribers on this cohort's "1:1 Call Booked" tag (the
                  reliable source - set on every booking incl. backfilled ones)
      - by_status: post-booking outcomes from the student record (Attended /
                  No-show / Rescheduled / Cancelled / Done). Plain "Booked" is
                  excluded here since `booked` is the headline count.
    Tags are resolved with exclude_future=True so a pre-created next-cohort tag
    (e.g. SEP-26) doesn't get read while JUN-26 is running.
    """
    by_status: dict = {}
    async for r in db.academy_members.aggregate([
        {"$match": {"bonus_call_status": {"$nin": [None, "", "Booked"]}}},
        {"$group": {"_id": "$bonus_call_status", "n": {"$sum": 1}}},
    ]):
        by_status[r["_id"]] = r["n"]

    async def _unique_tag_emails(suffixes: list[str]) -> int:
        emails: set = set()
        for suf in suffixes:
            tag_ids = await connectors._resolve_ayci_cohort_tags(suf, exclude_future=True)
            if tag_ids:
                emails |= await connectors._ck_tag_emails(tag_ids[0])
        return len(emails)

    eligible = booked = None
    try:
        eligible = await _unique_tag_emails(calendly_webhook.ELIGIBILITY_TAG_SUFFIXES)
    except Exception as e:
        logger.warning(f"[bonus-call] eligible count failed: {e}")
    try:
        booked = await _unique_tag_emails([calendly_webhook.KIT_BOOKED_TAG_SUFFIX])
    except Exception as e:
        logger.warning(f"[bonus-call] booked count failed: {e}")

    return {"eligible": eligible, "booked": booked, "by_status": by_status,
            "tracked": booked or 0}


@router.get("/bonus-call/summary")
async def bonus_call_summary(user: dict = Depends(get_current_user)):
    """Cached 30 min - the Kit eligibility count paginates a few tags."""
    return await launches_mod._stale_while_revalidate(
        db, "bonus_call_summary", ttl_min=30, compute_fn=_compute_bonus_summary,
    )


class LinkBookingBody(BaseModel):
    invitee_uri: str
    student_email: str


@router.get("/bonus-call/unmatched")
async def unmatched_bonus_bookings(user: dict = Depends(require_board("students"))):
    """Bonus-call bookings the dashboard couldn't tie to a student (booked under
    an email we'd never seen). The team links each to the right student."""
    rows = await db.calendly_events_seen.find(
        {"matched": False, "status": {"$in": ["booked", "rescheduled"]}},
        {"_id": 1, "email": 1, "name": 1, "coach": 1, "call_date": 1},
    ).sort("at", -1).to_list(100)
    return {"bookings": [
        {"invitee_uri": r["_id"], "email": r.get("email"), "name": r.get("name"),
         "coach": r.get("coach"), "date": r.get("call_date")}
        for r in rows
    ]}


@router.post("/bonus-call/link")
async def link_bonus_booking(body: LinkBookingBody,
                             user: dict = Depends(require_board("students"))):
    """Link an unmatched booking to a student: save the booking email onto their
    'Other emails' (so it auto-matches next time) and record the booking."""
    seen = await db.calendly_events_seen.find_one({"_id": body.invitee_uri})
    if not seen:
        raise HTTPException(404, "booking not found")
    target = (body.student_email or "").strip().lower()
    if not target:
        raise HTTPException(400, "student_email required")
    row = await db.academy_members.find_one({"$or": [
        {"email": target},
        {"circle_email": target},
        {"other_emails": {"$regex": re.escape(target), "$options": "i"}},
    ]})
    if not row:
        raise HTTPException(404, f"No student found for {target}")

    booking_email = (seen.get("email") or "").strip().lower()
    existing = [e.strip() for e in re.split(r"[,;]", row.get("other_emails") or "") if e.strip()]
    if booking_email and booking_email not in [e.lower() for e in existing]:
        existing.append(booking_email)
    coach = seen.get("coach")
    now = datetime.now(timezone.utc)
    fields = {
        "other_emails": ", ".join(existing) or None,
        "bonus_call": f"Booked - {coach}" if coach else "Booked",
        "bonus_call_coach": coach,
        "bonus_call_date": seen.get("call_date"),
        "bonus_call_status": "Booked",
    }
    pinned = sorted(set(row.get("dashboard_edited_fields") or []) | set(fields.keys()))
    await db.academy_members.update_one({"_id": row["_id"]}, {"$set": {
        **fields, "dashboard_edited_fields": pinned,
        "dashboard_edited_at": now, "dashboard_edited_by": "bonus-call-link",
    }})
    await db.calendly_events_seen.update_one(
        {"_id": body.invitee_uri},
        {"$set": {"matched": True, "linked_to": row["_id"], "linked_at": now}},
    )
    logger.info(f"[bonus-call] linked {booking_email} -> {row['_id']} ({row.get('name')})")
    return {"ok": True, "student_id": row["_id"], "name": row.get("name"),
            "added_email": booking_email}


@router.post("/admin/calendly/backfill-bonus-tags")
async def backfill_bonus_tags(admin: dict = Depends(require_admin)):
    """Catch up bookings missed while the Zapier zaps were off: tag every past/
    upcoming AYCI Bonus Call booker (Anoop + Charlotte) with the current cohort's
    '1:1 Call Booked' Kit tag and record bonus_call. Idempotent. Uses
    CALENDLY_TOKEN directly, so it works whether or not the live webhook is set."""
    if not os.environ.get("CALENDLY_TOKEN"):
        raise HTTPException(400, "CALENDLY_TOKEN not set")
    try:
        result = await calendly_webhook.backfill_bonus_call_tags(db)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"Calendly: {e.response.text[:200]}")
    except Exception as e:
        logger.exception("[calendly] backfill error")
        raise HTTPException(500, f"backfill failed: {str(e)[:200]}")
    return {"ok": True, **result}


# ----------------------------- Private Tier calls -------------------------

class PrivateCallStatusBody(BaseModel):
    email: str
    invitee_uri: str
    status: str


_PRIVATE_STATUSES = {"Booked", "Attended", "No-show", "Rescheduled", "Cancelled", "Done"}
_PRIVATE_KINDS = {"coach_30", "tessa_30", "mock_60"}


async def _find_student_by_email(email: str):
    email = (email or "").strip().lower()
    if not email:
        raise HTTPException(400, "email required")
    row = await db.academy_members.find_one({"$or": [
        {"email": email}, {"circle_email": email},
        {"other_emails": {"$regex": re.escape(email), "$options": "i"}}]})
    if not row:
        raise HTTPException(404, f"No student found for {email}")
    return row


class LogPrivateCallBody(BaseModel):
    email: str
    kind: str
    coach: str | None = None
    date: str | None = None
    status: str | None = "Attended"


@router.post("/private-call/log")
async def log_private_call(body: LogPrivateCallBody,
                           user: dict = Depends(require_board("students"))):
    """Log a private-tier call that wasn't booked via Calendly (counts as one of
    the student's eligible calls). Defaults to Attended."""
    kind = (body.kind or "").strip()
    if kind not in _PRIVATE_KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(_PRIVATE_KINDS)}")
    status = (body.status or "Attended").strip()
    if status not in _PRIVATE_STATUSES:
        raise HTTPException(400, f"status must be one of {sorted(_PRIVATE_STATUSES)}")
    row = await _find_student_by_email(body.email)
    entry = await calendly_webhook.add_manual_private_call(
        db, row, kind, body.coach, body.date, status)
    return {"ok": True, "entry": entry}


class GrantAllowanceBody(BaseModel):
    email: str
    kind: str
    delta: int = 1


@router.post("/private-call/grant")
async def grant_private_allowance(body: GrantAllowanceBody,
                                  user: dict = Depends(require_board("students"))):
    """Adjust a student's extra (above-tier) allowance for one call kind, e.g.
    grant a VIP a 3rd coach call. delta is usually +1 or -1."""
    kind = (body.kind or "").strip()
    if kind not in _PRIVATE_KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(_PRIVATE_KINDS)}")
    row = await _find_student_by_email(body.email)
    extra = await calendly_webhook.adjust_private_allowance(db, row, kind, int(body.delta))
    return {"ok": True, "extra": extra}


@router.post("/private-call/set-status")
async def set_private_call_status_endpoint(body: PrivateCallStatusBody,
                                           user: dict = Depends(require_board("students"))):
    """Coach action: set the outcome (Attended / No-show / etc.) of one private-
    tier call on a student, keyed by the booking's invitee_uri."""
    status = (body.status or "").strip()
    if status not in _PRIVATE_STATUSES:
        raise HTTPException(400, f"status must be one of {sorted(_PRIVATE_STATUSES)}")
    email = (body.email or "").strip().lower()
    if not email or not (body.invitee_uri or "").strip():
        raise HTTPException(400, "email and invitee_uri required")
    row = await db.academy_members.find_one({"$or": [
        {"email": email}, {"circle_email": email},
        {"other_emails": {"$regex": re.escape(email), "$options": "i"}}]})
    if not row:
        raise HTTPException(404, f"No student found for {email}")
    ok = await calendly_webhook.set_private_call_status(db, row, body.invitee_uri, status)
    if not ok:
        raise HTTPException(404, "No matching call on that student")
    logger.info(f"[private-call] {email} call {body.invitee_uri} -> {status}")
    return {"ok": True, "status": status}


@router.post("/admin/calendly/backfill-private-calls")
async def backfill_private_calls_endpoint(admin: dict = Depends(require_admin)):
    """Catch up private-tier (Private Plus / VIP) bookings: scan past/upcoming
    Calendly events, classify the private-tier ones, and record each on the
    matching student's private_calls array. Idempotent. No Kit tag.

    Runs in the BACKGROUND (the private-tier calendar runs year-round, so the
    scan makes many Calendly calls and would otherwise outlast the request) and
    posts a summary to #fulfillment-team when it finishes."""
    if not os.environ.get("CALENDLY_TOKEN"):
        raise HTTPException(400, "CALENDLY_TOKEN not set")

    async def _run():
        try:
            res = await calendly_webhook.backfill_private_calls(db)
            msg = (f":white_check_mark: *Private-tier backfill done* - recorded "
                   f"{res.get('recorded', 0)} bookings across {res.get('private_events', 0)} "
                   f"private-tier events"
                   + (f"; {res.get('not_found', 0)} not matched to a student" if res.get("not_found") else "")
                   + (f". {res.get('error')}" if res.get("error") else "."))
        except httpx.HTTPStatusError as e:
            logger.warning(f"[calendly] private backfill HTTP {e.response.status_code}: {e.response.text[:300]}")
            msg = f":x: *Private-tier backfill failed* - Calendly {e.response.status_code}: {e.response.text[:160]}"
        except Exception as e:
            logger.exception("[calendly] private backfill error")
            msg = f":x: *Private-tier backfill failed* - {str(e)[:200]}"
        try:
            await slack_dm.post_to_channel(db, "#fulfillment-team", msg)
        except Exception:
            logger.warning("[calendly] couldn't post private-backfill summary to Slack")

    asyncio.create_task(_run())
    return {"ok": True, "started": True}


async def _compute_private_summary() -> dict:
    """Roll-up of private-tier call bookings across all students, broken down by
    call kind, coach, tier, month, and status. 'active' excludes Cancelled /
    No-show. Drives the data-tracking summary."""
    rows = []
    async for r in db.academy_members.aggregate([
        {"$match": {"private_calls": {"$exists": True, "$ne": []}}},
        {"$unwind": "$private_calls"},
        {"$group": {"_id": {
            "kind": "$private_calls.kind",
            "coach": "$private_calls.coach",
            "tier": "$tier",
            "status": "$private_calls.status",
            "month": {"$substr": [{"$ifNull": ["$private_calls.date", ""]}, 0, 7]},
        }, "n": {"$sum": 1}}},
    ]):
        rows.append((r["_id"], r["n"]))

    by_kind, by_coach, by_tier, by_status, by_month = {}, {}, {}, {}, {}
    active = 0
    for k, n in rows:
        st = k.get("status") or "?"
        by_status[st] = by_status.get(st, 0) + n
        if st in ("Cancelled", "No-show"):
            continue
        active += n
        kind = k.get("kind") or "?"
        coach = k.get("coach") or "?"
        tier = calendly_webhook._normalize_tier(k.get("tier")) or "?"
        mo = k.get("month") or "?"
        by_kind[kind] = by_kind.get(kind, 0) + n
        by_coach[coach] = by_coach.get(coach, 0) + n
        by_tier[tier] = by_tier.get(tier, 0) + n
        by_month[mo] = by_month.get(mo, 0) + n

    students = await db.academy_members.count_documents(
        {"private_calls": {"$elemMatch": {"status": {"$nin": ["Cancelled", "No-show"]}}}})
    return {"active_calls": active, "students_with_calls": students,
            "by_kind": by_kind, "by_coach": by_coach, "by_tier": by_tier,
            "by_status": by_status, "by_month": by_month,
            "kind_labels": calendly_webhook.PRIVATE_KIND_LABELS}


@router.get("/private-call/summary")
async def private_call_summary(user: dict = Depends(get_current_user)):
    """Cached 15 min - aggregates the private_calls arrays across all students."""
    return await launches_mod._stale_while_revalidate(
        db, "private_call_summary", ttl_min=15, compute_fn=_compute_private_summary,
    )


@router.get("/admin/calendly/status")
async def calendly_status(admin: dict = Depends(require_admin)):
    """Whether the bonus-call webhook has been registered (drives the
    Settings → Integrations "Connect Calendly" card)."""
    doc = await db.app_settings.find_one(
        {"id": "calendly_webhook"},
        {"_id": 0, "callback": 1, "subscription_uri": 1, "signing_key": 1},
    ) or {}
    return {
        "connected": bool(doc.get("signing_key")),
        "callback": doc.get("callback"),
        "subscription_uri": doc.get("subscription_uri"),
    }


@router.get("/admin/calendly/event-types")
async def calendly_event_types(admin: dict = Depends(require_admin)):
    """Diagnostic: list the org's active Calendly event types with how the
    dashboard classifies each booking (bonus_call / coach_30 / tessa_30 /
    mock_60 / untracked). Use this to confirm the private-tier events are
    matched correctly - 'untracked' on a call event means a booking on it
    won't be logged."""
    if not os.environ.get("CALENDLY_TOKEN"):
        raise HTTPException(400, "CALENDLY_TOKEN not set")
    out = []
    async with httpx.AsyncClient(timeout=30) as c:
        me = await c.get(f"{connectors.CALENDLY_BASE}/users/me",
                         headers=connectors._calendly_headers())
        me.raise_for_status()
        org = (me.json().get("resource") or {}).get("current_organization")
        url = f"{connectors.CALENDLY_BASE}/event_types"
        params = {"organization": org, "count": 100, "active": "true"}
        while url:
            r = await c.get(url, headers=connectors._calendly_headers(), params=params)
            r.raise_for_status()
            body = r.json()
            for et in body.get("collection", []):
                name = et.get("name") or ""
                slug = et.get("slug") or ""
                is_bonus = calendly_webhook.BONUS_EVENT_MATCH in name.lower()
                kind = None if is_bonus else calendly_webhook._classify_private_event(name, slug)
                out.append({
                    "name": name,
                    "slug": slug,
                    "duration": et.get("duration"),
                    "scheduling_url": et.get("scheduling_url"),
                    "classified_as": "bonus_call" if is_bonus else (kind or "untracked"),
                })
            url = (body.get("pagination") or {}).get("next_page")
            params = None
    out.sort(key=lambda e: (e["classified_as"] == "untracked", e["name"]))
    return {"event_types": out, "labels": calendly_webhook.PRIVATE_KIND_LABELS}


@router.get("/admin/calendly/webhooks")
async def list_calendly_webhooks(admin: dict = Depends(require_admin)):
    """List current org webhook subscriptions (diagnostic / cleanup)."""
    async with httpx.AsyncClient(timeout=30) as c:
        me = await c.get(f"{connectors.CALENDLY_BASE}/users/me",
                         headers=connectors._calendly_headers())
        me.raise_for_status()
        org = (me.json().get("resource") or {}).get("current_organization")
        r = await c.get(f"{connectors.CALENDLY_BASE}/webhook_subscriptions",
                        headers=connectors._calendly_headers(),
                        params={"organization": org, "scope": "organization"})
    return r.json()
