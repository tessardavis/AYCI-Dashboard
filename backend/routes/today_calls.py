"""Today's Calls — REST endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import today_calls as tc
from db import db
from deps import require_board

router = APIRouter(prefix="/api/today-calls", tags=["today-calls"])


class ManualCallCreate(BaseModel):
    student_name: str = Field(..., min_length=1, max_length=200)
    student_email: str = Field(..., min_length=3, max_length=320)
    host: str = Field(..., min_length=1, max_length=100)
    starts_at: str = Field(..., min_length=10, max_length=40)  # ISO-8601 UTC
    duration_min: int = Field(default=30, ge=5, le=240)
    notes: str | None = Field(default=None, max_length=500)


@router.get("")
async def list_calls(user: dict = Depends(require_board("coach_activity"))):
    return {"items": await tc.list_today_calls(db)}


@router.post("/manual")
async def create_manual(
    payload: ManualCallCreate,
    user: dict = Depends(require_board("coach_activity")),
):
    if "@" not in payload.student_email:
        raise HTTPException(400, "Valid email required")
    return await tc.add_manual_call(
        db,
        student_name=payload.student_name,
        student_email=payload.student_email,
        host=payload.host,
        starts_at=payload.starts_at,
        duration_min=payload.duration_min,
        notes=payload.notes,
        created_by=user.get("id"),
    )


@router.delete("/manual/{call_id}")
async def delete_manual(
    call_id: str,
    user: dict = Depends(require_board("coach_activity")),
):
    return await tc.delete_manual_call(db, call_id)
