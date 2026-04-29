"""Quarterly Rocks CRUD."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException

from db import db
from deps import get_current_user, require_admin
from models import Rock, RockCreate, RockUpdate

router = APIRouter(prefix="/api", tags=["rocks"])


@router.get("/rocks", response_model=List[Rock])
async def list_rocks(quarter: Optional[str] = None, user: dict = Depends(get_current_user)):
    q = {"quarter": quarter} if quarter else {}
    return await db.rocks.find(q, {"_id": 0}).to_list(1000)


@router.get("/rocks/quarters")
async def list_quarters(user: dict = Depends(get_current_user)):
    quarters = await db.rocks.distinct("quarter")
    return sorted(quarters, reverse=True)


@router.post("/rocks", response_model=Rock)
async def create_rock(data: RockCreate, admin: dict = Depends(require_admin)):
    r = Rock(**data.model_dump())
    await db.rocks.insert_one(r.model_dump())
    return r


@router.patch("/rocks/{rock_id}", response_model=Rock)
async def update_rock(rock_id: str, data: RockUpdate, user: dict = Depends(get_current_user)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        await db.rocks.update_one({"id": rock_id}, {"$set": updates})
    doc = await db.rocks.find_one({"id": rock_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return doc


@router.delete("/rocks/{rock_id}")
async def delete_rock(rock_id: str, admin: dict = Depends(require_admin)):
    await db.rocks.delete_one({"id": rock_id})
    return {"ok": True}
