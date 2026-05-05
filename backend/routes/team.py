"""Team members CRUD."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from db import db
from deps import get_current_user, require_admin
from models import TeamMember, TeamMemberCreate

router = APIRouter(prefix="/api", tags=["team"])


@router.get("/team", response_model=List[TeamMember])
async def list_team(user: dict = Depends(get_current_user)):
    return await db.team_members.find({}, {"_id": 0}).to_list(1000)


@router.post("/team", response_model=TeamMember)
async def create_team_member(data: TeamMemberCreate, admin: dict = Depends(require_admin)):
    tm = TeamMember(**data.model_dump())
    await db.team_members.insert_one(tm.model_dump())
    return tm


@router.patch("/team/{member_id}", response_model=TeamMember)
async def update_team_member(member_id: str, data: TeamMemberCreate, admin: dict = Depends(require_admin)):
    await db.team_members.update_one({"id": member_id}, {"$set": data.model_dump()})
    doc = await db.team_members.find_one({"id": member_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return doc


@router.delete("/team/{member_id}")
async def delete_team_member(member_id: str, admin: dict = Depends(require_admin)):
    await db.team_members.delete_one({"id": member_id})
    return {"ok": True}



# ---- Inbox auto-routing rules (Gmail → assignee) -------------------------
import settings_store  # noqa: E402


@router.get("/team/inbox-routing")
async def get_inbox_routing(user: dict = Depends(get_current_user)):
    return {"rules": await settings_store.get_inbox_routing(db)}


@router.put("/team/inbox-routing")
async def put_inbox_routing(payload: dict, admin: dict = Depends(require_admin)):
    rules = payload.get("rules") or []
    if not isinstance(rules, list):
        raise HTTPException(400, "rules must be a list")
    saved = await settings_store.set_inbox_routing(db, rules)
    return {"rules": saved}
