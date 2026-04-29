"""Quarterly Rocks CRUD with per-user owner editing + quarter archiving."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException

import settings_store
from db import db
from deps import get_current_user, require_admin
from models import Rock, RockCreate, RockUpdate

router = APIRouter(prefix="/api", tags=["rocks"])


async def _can_edit_rock(rock: dict, user: dict) -> bool:
    """Edit rules:
    - Admin can always edit.
    - For active quarter: any user whose linked team_member_id is in
      `rock.owner_ids` can edit (rocks store a single owner_id, so we check
      that field). Strangers see read-only.
    - For non-active (archived) quarter: admin only.
    """
    if user.get("role") == "admin":
        return True
    active = await settings_store.get_active_quarter(db)
    if rock.get("quarter") != active:
        return False  # archived → admin only
    user_tm = user.get("team_member_id")
    if not user_tm:
        return False
    return rock.get("owner_id") == user_tm


@router.get("/rocks", response_model=List[Rock])
async def list_rocks(quarter: Optional[str] = None, user: dict = Depends(get_current_user)):
    q = {"quarter": quarter} if quarter else {}
    return await db.rocks.find(q, {"_id": 0}).to_list(1000)


@router.get("/rocks/quarters")
async def list_quarters(user: dict = Depends(get_current_user)):
    """Return all quarters + active flag so the UI can show 'archived' badges."""
    quarters = await db.rocks.distinct("quarter")
    quarters = sorted(quarters, reverse=True)
    active = await settings_store.get_active_quarter(db, fallback_quarters=quarters)
    return {"quarters": quarters, "active": active}


@router.post("/rocks", response_model=Rock)
async def create_rock(data: RockCreate, user: dict = Depends(get_current_user)):
    """Create a rock. Non-admins can only create rocks in the active quarter
    AND must be creating a rock for themselves (owner_id == their team_member_id)."""
    active = await settings_store.get_active_quarter(db)
    if user.get("role") != "admin":
        if data.quarter != active:
            raise HTTPException(403, "Only admins can edit archived quarters")
        if data.owner_id != user.get("team_member_id"):
            raise HTTPException(403, "You can only create rocks for yourself")
    r = Rock(**data.model_dump())
    await db.rocks.insert_one(r.model_dump())
    return r


@router.patch("/rocks/{rock_id}", response_model=Rock)
async def update_rock(rock_id: str, data: RockUpdate, user: dict = Depends(get_current_user)):
    rock = await db.rocks.find_one({"id": rock_id}, {"_id": 0})
    if not rock:
        raise HTTPException(status_code=404, detail="Not found")
    if not await _can_edit_rock(rock, user):
        raise HTTPException(status_code=403, detail="Not allowed to edit this rock")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    # Non-admins can't reassign ownership or move rocks across quarters.
    if user.get("role") != "admin":
        for forbidden in ("owner_id", "quarter"):
            if forbidden in updates:
                del updates[forbidden]
    if updates:
        await db.rocks.update_one({"id": rock_id}, {"$set": updates})
    doc = await db.rocks.find_one({"id": rock_id}, {"_id": 0})
    return doc


@router.delete("/rocks/{rock_id}")
async def delete_rock(rock_id: str, user: dict = Depends(get_current_user)):
    rock = await db.rocks.find_one({"id": rock_id}, {"_id": 0})
    if not rock:
        return {"ok": True}
    if not await _can_edit_rock(rock, user):
        raise HTTPException(status_code=403, detail="Not allowed to delete this rock")
    await db.rocks.delete_one({"id": rock_id})
    return {"ok": True}


# --- Active quarter management (admin only) -------------------------------
@router.put("/rocks/active-quarter")
async def set_active_quarter(payload: dict, admin: dict = Depends(require_admin)):
    """Admin-only: set which quarter is currently active. All other quarters
    become read-only (archived) for non-admin users."""
    quarter = (payload.get("quarter") or "").strip()
    if not quarter:
        raise HTTPException(400, "quarter is required")
    saved = await settings_store.set_active_quarter(db, quarter)
    return {"active": saved}
