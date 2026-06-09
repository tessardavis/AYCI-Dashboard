"""
Refunds board — Coralie's space to track refunds, reasons and outcomes.

Source of truth is Stripe: a refund issued in Stripe flows in via a Zapier
"Stripe → New Refund" trigger that POSTs to `/api/refunds/ingest` with the
shared ZAPIER_WEBHOOK_SECRET (same secret as the students-db zaps). We match
the refund to a student by email and snapshot their name / tier / cohort so
the record is self-contained even if the student row later changes. Coralie
then fills in the reason category + notes and moves it through a small status
workflow.

Routes:
  POST   /api/refunds/ingest        Zapier/Stripe-callable upsert (secret)
  GET    /api/refunds               list (board: refunds), filters + search
  GET    /api/refunds/summary       totals by status / category (board)
  PATCH  /api/refunds/{refund_id}   edit reason/category/status/notes (board)
  DELETE /api/refunds/{refund_id}   remove a record (admin only)
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from db import db
from deps import require_board, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["refunds"])

# The workflow states a refund can move through. Stripe-ingested refunds land
# as "processed" (Stripe already moved the money); the others let Coralie log
# refunds that are still being decided.
REFUND_STATUSES = ["requested", "approved", "processed", "declined"]

# Editable by the board UI (everything else is snapshot/ingest data).
EDITABLE_FIELDS = {"reason_category", "reason_notes", "status"}


def _check_webhook_secret(x_webhook_secret: Optional[str]) -> None:
    expected = (os.environ.get("ZAPIER_WEBHOOK_SECRET") or "").strip()
    if not expected:
        raise HTTPException(503, "Webhook auth not configured")
    if (x_webhook_secret or "").strip() != expected:
        raise HTTPException(401, "Invalid webhook secret")


def _coerce_amount(body: dict) -> Optional[float]:
    """Stripe sends amounts as integer minor units (e.g. 14900 = £149.00) on
    `amount` / `amount_refunded`. Zapier users sometimes map a pre-formatted
    major-unit value ("149.00") instead. Accept both:

      • amount_refunded / amount_cents / amount_minor → divide by 100
      • amount (with a decimal point, or an explicit major flag) → as-is
    """
    for k in ("amount_refunded", "amount_cents", "amount_minor"):
        v = body.get(k)
        if v not in (None, ""):
            try:
                return round(int(float(v)) / 100.0, 2)
            except (ValueError, TypeError):
                pass
    v = body.get("amount")
    if v in (None, ""):
        return None
    try:
        f = float(v)
    except (ValueError, TypeError):
        return None
    # A bare integer with no decimal that looks like minor units is ambiguous;
    # we treat `amount` as already being major units (what Zapier's formatted
    # field gives). Callers wanting minor units should use amount_refunded.
    return round(f, 2)


def _norm_date(val: Any) -> Optional[str]:
    """Accept an ISO string or a Unix timestamp (Stripe `created`) → ISO."""
    if val in (None, ""):
        return None
    s = str(val).strip()
    if s.isdigit() and len(s) >= 9:  # unix seconds
        try:
            return datetime.fromtimestamp(int(s), tz=timezone.utc).isoformat()
        except (ValueError, OverflowError):
            return None
    return s


async def _student_snapshot(email_l: str) -> dict:
    """Best-effort student match → name / tier / cohort snapshot."""
    if not email_l:
        return {}
    row = await db.academy_members.find_one(
        {"$or": [{"email": email_l}, {"circle_email": email_l}]},
        {"_id": 1, "name": 1, "tier": 1, "cohort_joined": 1},
    )
    if not row:
        return {}
    return {
        "student_monday_id": row.get("_id"),
        "student_name": row.get("name"),
        "tier": row.get("tier"),
        "cohort": row.get("cohort_joined"),
    }


@router.post("/refunds/ingest")
async def ingest_refund(
    request: Request,
    x_webhook_secret: Optional[str] = Header(default=None, alias="X-Webhook-Secret"),
):
    """Upsert a refund from Stripe (via Zapier). Dedups on the Stripe refund
    id so a re-sent zap doesn't create duplicates. Accepts flat Zapier-style
    keys or a nested object."""
    _check_webhook_secret(x_webhook_secret)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")
    if not isinstance(body, dict):
        raise HTTPException(400, "payload must be an object")

    email_l = str(
        body.get("email") or body.get("customer_email")
        or body.get("receipt_email") or ""
    ).strip().lower()

    stripe_refund_id = str(
        body.get("stripe_refund_id") or body.get("refund_id") or body.get("id") or ""
    ).strip() or None

    snap = await _student_snapshot(email_l)
    amount = _coerce_amount(body)
    currency = str(body.get("currency") or "gbp").strip().lower()
    refunded_at = _norm_date(
        body.get("refunded_at") or body.get("created") or body.get("date")
    ) or datetime.now(timezone.utc).isoformat()

    # Stripe's machine reason (duplicate / fraudulent / requested_by_customer)
    # seeds the category; Coralie can refine it on the board.
    stripe_reason = (body.get("reason") or "").strip() or None

    now = datetime.now(timezone.utc).isoformat()
    set_doc: dict[str, Any] = {
        "student_email": email_l or None,
        "student_name": body.get("student_name") or body.get("customer_name") or snap.get("student_name"),
        "student_monday_id": snap.get("student_monday_id"),
        "tier": snap.get("tier"),
        "cohort": snap.get("cohort"),
        "amount": amount,
        "currency": currency,
        "refunded_at": refunded_at,
        "stripe_refund_id": stripe_refund_id,
        "stripe_charge_id": (str(body.get("charge") or body.get("stripe_charge_id") or "").strip() or None),
        "stripe_reason": stripe_reason,
        "source": "stripe",
        "updated_at": now,
    }

    # Upsert by Stripe refund id when we have one; else always insert.
    if stripe_refund_id:
        existing = await db.refunds.find_one(
            {"stripe_refund_id": stripe_refund_id}, {"_id": 0, "id": 1}
        )
    else:
        existing = None

    if existing:
        await db.refunds.update_one(
            {"id": existing["id"]}, {"$set": set_doc}
        )
        logger.info(f"[refunds] updated refund id={existing['id']} email={email_l}")
        return {"ok": True, "id": existing["id"], "created": False,
                "matched_student": bool(snap)}

    refund_id = str(uuid.uuid4())
    doc = {
        "id": refund_id,
        **set_doc,
        # Coralie-managed fields start empty so the board surfaces them.
        "reason_category": stripe_reason,
        "reason_notes": None,
        "status": "processed",
        "created_at": now,
    }
    await db.refunds.insert_one(doc)
    logger.info(f"[refunds] created refund id={refund_id} email={email_l} matched={bool(snap)}")
    return {"ok": True, "id": refund_id, "created": True, "matched_student": bool(snap)}


@router.get("/refunds/summary")
async def refunds_summary(user: dict = Depends(require_board("refunds"))):
    """Totals for the board header: count + amount by status and by category."""
    by_status: dict[str, int] = {}
    by_category: dict[str, dict] = {}
    total_amount = 0.0
    total_count = 0
    needs_reason = 0
    currency = "gbp"
    async for r in db.refunds.find({}, {"_id": 0, "status": 1, "amount": 1,
                                        "reason_category": 1, "currency": 1}):
        total_count += 1
        amt = r.get("amount") or 0
        total_amount += amt
        if r.get("currency"):
            currency = r["currency"]
        st = r.get("status") or "processed"
        by_status[st] = by_status.get(st, 0) + 1
        cat = (r.get("reason_category") or "").strip()
        if not cat:
            needs_reason += 1
            cat = "(no reason yet)"
        slot = by_category.setdefault(cat, {"count": 0, "amount": 0.0})
        slot["count"] += 1
        slot["amount"] = round(slot["amount"] + amt, 2)
    return {
        "total_count": total_count,
        "total_amount": round(total_amount, 2),
        "currency": currency,
        "needs_reason": needs_reason,
        "by_status": by_status,
        "by_category": by_category,
    }


@router.get("/refunds")
async def list_refunds(
    q: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    needs_reason: Optional[bool] = None,
    limit: int = 1000,
    user: dict = Depends(require_board("refunds")),
):
    query: dict = {}
    if status:
        query["status"] = status
    if category:
        query["reason_category"] = category
    if needs_reason is True:
        query["$or"] = [{"reason_category": None}, {"reason_category": ""}]
    if q:
        rx = {"$regex": q, "$options": "i"}
        text_or = [{"student_name": rx}, {"student_email": rx},
                   {"stripe_refund_id": rx}, {"reason_notes": rx}]
        if "$or" in query:
            query = {"$and": [{"$or": query.pop("$or")}, {"$or": text_or}]}
        else:
            query["$or"] = text_or
    cursor = (
        db.refunds.find(query, {"_id": 0})
        .sort([("refunded_at", -1)])
        .limit(min(limit, 5000))
    )
    items = [r async for r in cursor]
    return {"items": items, "count": len(items)}


class RefundPatch(BaseModel):
    reason_category: Optional[str] = None
    reason_notes: Optional[str] = None
    status: Optional[str] = None


@router.patch("/refunds/{refund_id}")
async def update_refund(
    refund_id: str,
    patch: RefundPatch,
    user: dict = Depends(require_board("refunds")),
):
    fields = {k: v for k, v in patch.dict(exclude_unset=True).items() if k in EDITABLE_FIELDS}
    if not fields:
        raise HTTPException(400, "No editable fields supplied")
    if "status" in fields and fields["status"] not in REFUND_STATUSES:
        raise HTTPException(400, f"status must be one of {REFUND_STATUSES}")
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    fields["updated_by"] = user.get("email") or user.get("id")
    res = await db.refunds.update_one({"id": refund_id}, {"$set": fields})
    if res.matched_count == 0:
        raise HTTPException(404, "Refund not found")
    doc = await db.refunds.find_one({"id": refund_id}, {"_id": 0})
    return {"ok": True, "refund": doc}


@router.delete("/refunds/{refund_id}")
async def delete_refund(refund_id: str, admin: dict = Depends(require_admin)):
    res = await db.refunds.delete_one({"id": refund_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Refund not found")
    return {"ok": True}
