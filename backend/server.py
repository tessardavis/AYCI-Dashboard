from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import uuid
import logging
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Literal

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr

import connectors
import student_lookup as lookup
import upcoming_interviews as upcoming
import coach_activity as coach_act
import onboarding_gap as ob_gap
import scorecard_auto
import cohort as cohort_mod
import google_drive as gdrive
import launches as launches_mod
import at_risk as at_risk_mod
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# --- MongoDB ----------------------------------------------------------------
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

# --- App --------------------------------------------------------------------
app = FastAPI(title="AYCI Team Dashboard")
api = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- Auth helpers -----------------------------------------------------------
JWT_ALGORITHM = "HS256"


def jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        "type": "access",
    }
    return jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "refresh",
    }
    return jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGORITHM)


def set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    response.set_cookie("access_token", access, httponly=True, secure=False, samesite="lax", max_age=60 * 60 * 24, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=False, samesite="lax", max_age=60 * 60 * 24 * 7, path="/")


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return user


# All boards in the app. Admin-only boards (settings) are not in DEFAULT_BOARDS.
ALL_BOARDS = [
    "weekly_scorecard",
    "quarterly_rocks",
    "launches",
    "cohort",
    "interviews",
    "students",
    "at_risk",
    "coach_activity",
]
ADMIN_ONLY_BOARDS = ["settings"]


def user_has_board(user: dict, board: str) -> bool:
    """Admins always pass. Members must have the board in their board_access list."""
    if user.get("role") == "admin":
        return True
    if board in ADMIN_ONLY_BOARDS:
        return False
    return board in (user.get("board_access") or [])


def require_board(board: str):
    """FastAPI dependency factory: ensures the current user can access `board`."""
    async def _check(user: dict = Depends(get_current_user)) -> dict:
        if not user_has_board(user, board):
            raise HTTPException(status_code=403, detail=f"Access to '{board}' board is not granted")
        return user
    return _check


# --- Models -----------------------------------------------------------------
class LoginInput(BaseModel):
    email: EmailStr
    password: str


class RegisterInput(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: Literal["admin", "user"] = "user"
    board_access: List[str] = Field(default_factory=list)


class UserOut(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: str
    board_access: List[str] = Field(default_factory=list)


class UserPatch(BaseModel):
    name: Optional[str] = None
    role: Optional[Literal["admin", "user"]] = None
    board_access: Optional[List[str]] = None
    password: Optional[str] = None  # set new password


class ChangePasswordInput(BaseModel):
    current_password: str
    new_password: str


class TeamMember(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    role_title: str
    avatar_url: Optional[str] = None


class TeamMemberCreate(BaseModel):
    name: str
    role_title: str
    avatar_url: Optional[str] = None


MetricFormat = Literal["number", "currency", "percentage"]
MetricCategory = Literal["GROWTH + INTEREST", "CONVERSION + INTENT", "REVENUE", "SOCIAL PROOF", "DELIVERY + OPERATIONS"]


class Metric(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    category: MetricCategory
    owner_ids: List[str] = []
    goal: Optional[float] = 0
    format: MetricFormat = "number"
    order: int = 0
    goal_direction: Literal["above", "below"] = "above"
    source_type: Optional[str] = None  # e.g. "convertkit_tag_new_subscribers"
    source_params: Optional[dict] = None  # connector-specific config
    # Hide from weekly view (e.g. cohort-only metrics surveyed once per cohort)
    cohort_only: bool = False
    # Whether the metric value can be auto-computed via /scorecard/auto-compute
    is_auto: bool = False


class MetricCreate(BaseModel):
    name: str
    category: MetricCategory
    owner_ids: List[str] = []
    goal: Optional[float] = 0
    format: MetricFormat = "number"
    goal_direction: Literal["above", "below"] = "above"
    source_type: Optional[str] = None
    source_params: Optional[dict] = None
    cohort_only: bool = False
    is_auto: bool = False


class MetricUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[MetricCategory] = None
    owner_ids: Optional[List[str]] = None
    goal: Optional[float] = None
    format: Optional[MetricFormat] = None
    order: Optional[int] = None
    goal_direction: Optional[Literal["above", "below"]] = None
    source_type: Optional[str] = None
    source_params: Optional[dict] = None


class WeeklyValue(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    metric_id: str
    week_start: str  # ISO date YYYY-MM-DD (Monday)
    value: float


class WeeklyValueInput(BaseModel):
    metric_id: str
    week_start: str
    value: float


RockStatus = Literal["on_track", "off_track", "done"]


class Rock(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    owner_id: str
    title: str
    status: RockStatus = "on_track"
    due_date: str  # ISO date
    notes: str = ""
    quarter: str  # e.g. "Q2 2026"


class RockCreate(BaseModel):
    owner_id: str
    title: str
    status: RockStatus = "on_track"
    due_date: str
    notes: str = ""
    quarter: str


class RockUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[RockStatus] = None
    due_date: Optional[str] = None
    notes: Optional[str] = None
    owner_id: Optional[str] = None


class LaunchPhase(BaseModel):
    start: Optional[str] = None  # YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ
    end: Optional[str] = None


class LaunchPhases(BaseModel):
    in_between_start: LaunchPhase = Field(default_factory=LaunchPhase)
    early_access: LaunchPhase = Field(default_factory=LaunchPhase)
    flash_sale: LaunchPhase = Field(default_factory=LaunchPhase)
    webinar: LaunchPhase = Field(default_factory=LaunchPhase)
    open_cart: LaunchPhase = Field(default_factory=LaunchPhase)
    close_cart: LaunchPhase = Field(default_factory=LaunchPhase)
    in_between_end: LaunchPhase = Field(default_factory=LaunchPhase)
    # Legacy fields kept for backwards-compat reads from existing DB rows.
    # New launches should use the keys above.
    early_signups: Optional[LaunchPhase] = None
    legacy_upgrades: Optional[LaunchPhase] = None
    in_between: Optional[LaunchPhase] = None


class Launch(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str  # human-readable, e.g. "April 2026"
    code: Optional[str] = None  # Kit tag prefix code, e.g. "APR-26"
    start_date: str   # overall launch start (early signups start)
    end_date: Optional[str] = None  # overall launch end
    webinar_date: str
    target_good: float
    target_better: float
    target_best: float
    phases: Optional[LaunchPhases] = None


class LaunchCreate(BaseModel):
    name: str
    code: Optional[str] = None
    start_date: str
    end_date: Optional[str] = None
    webinar_date: str
    target_good: float
    target_better: float
    target_best: float
    phases: Optional[LaunchPhases] = None


class LaunchUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    webinar_date: Optional[str] = None
    target_good: Optional[float] = None
    target_better: Optional[float] = None
    target_best: Optional[float] = None
    phases: Optional[LaunchPhases] = None


class LaunchData(BaseModel):
    """Per-launch aggregate data."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    launch_id: str
    total_registrations: float = 0
    webinar_attendance_rate: float = 0  # percentage
    sales_academy_count: float = 0
    sales_private_plus_count: float = 0
    sales_vip_count: float = 0
    sales_boost_count: float = 0
    upgrade_count: float = 0
    upsell_count: float = 0


class LaunchDataUpdate(BaseModel):
    total_registrations: Optional[float] = None
    webinar_attendance_rate: Optional[float] = None
    sales_academy_count: Optional[float] = None
    sales_private_plus_count: Optional[float] = None
    sales_vip_count: Optional[float] = None
    sales_boost_count: Optional[float] = None
    upgrade_count: Optional[float] = None
    upsell_count: Optional[float] = None


class DailyRegistration(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    launch_id: str
    date: str  # ISO date
    count: float


class DailyRegistrationInput(BaseModel):
    launch_id: str
    date: str
    count: float


# --- Auth endpoints ---------------------------------------------------------
@api.post("/auth/login")
async def login(data: LoginInput, response: Response):
    email = data.email.lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(data.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    access = create_access_token(user["id"], user["email"], user.get("role", "user"))
    refresh = create_refresh_token(user["id"])
    set_auth_cookies(response, access, refresh)
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user.get("role", "user"),
        "board_access": user.get("board_access") or [],
    }


@api.post("/auth/register")
async def register(data: RegisterInput, response: Response, admin: dict = Depends(require_admin)):
    email = data.email.lower()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    invalid = [b for b in (data.board_access or []) if b not in ALL_BOARDS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unknown boards: {invalid}")
    user_doc = {
        "id": str(uuid.uuid4()),
        "email": email,
        "name": data.name,
        "role": data.role,
        # Admins implicitly have all boards; for "user" we honour what was passed.
        "board_access": list(data.board_access or []),
        "password_hash": hash_password(data.password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(user_doc)
    return {
        "id": user_doc["id"],
        "email": email,
        "name": data.name,
        "role": data.role,
        "board_access": user_doc["board_access"],
    }


@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name"),
        "role": user.get("role", "user"),
        "board_access": (
            ALL_BOARDS + ADMIN_ONLY_BOARDS
            if user.get("role") == "admin"
            else (user.get("board_access") or [])
        ),
    }


# --- User admin (admin-only) -----------------------------------------------
@api.get("/admin/users")
async def admin_list_users(admin: dict = Depends(require_admin)):
    users = await db.users.find(
        {}, {"_id": 0, "password_hash": 0}
    ).sort("created_at", 1).to_list(500)
    # Normalise older docs that don't have board_access
    for u in users:
        u["board_access"] = u.get("board_access") or []
    return {"users": users, "all_boards": ALL_BOARDS}


@api.patch("/admin/users/{user_id}")
async def admin_update_user(
    user_id: str, data: UserPatch, admin: dict = Depends(require_admin)
):
    update: dict = {}
    if data.name is not None:
        update["name"] = data.name
    if data.role is not None:
        update["role"] = data.role
    if data.board_access is not None:
        invalid = [b for b in data.board_access if b not in ALL_BOARDS]
        if invalid:
            raise HTTPException(status_code=400, detail=f"Unknown boards: {invalid}")
        update["board_access"] = data.board_access
    if data.password:
        update["password_hash"] = hash_password(data.password)
    if not update:
        raise HTTPException(status_code=400, detail="No changes")

    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Safety: never let an admin demote themselves while being the only admin
    if (
        data.role == "user"
        and target.get("role") == "admin"
        and target.get("id") == admin.get("id")
    ):
        admin_count = await db.users.count_documents({"role": "admin"})
        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Can't demote the last admin. Promote another user first.",
            )

    await db.users.update_one({"id": user_id}, {"$set": update})
    fresh = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    fresh["board_access"] = fresh.get("board_access") or []
    return fresh


@api.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: str, admin: dict = Depends(require_admin)):
    if user_id == admin.get("id"):
        raise HTTPException(status_code=400, detail="You can't delete yourself.")
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.get("role") == "admin":
        admin_count = await db.users.count_documents({"role": "admin"})
        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Can't delete the last admin.",
            )
    await db.users.delete_one({"id": user_id})
    return {"ok": True}


@api.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"ok": True}


@api.post("/auth/change-password")
async def change_password(
    data: ChangePasswordInput,
    user: dict = Depends(get_current_user),
):
    """Self-serve password change for the logged-in user."""
    new_pw = (data.new_password or "").strip()
    if len(new_pw) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    if new_pw == data.current_password:
        raise HTTPException(status_code=400, detail="New password must differ from current")
    # Re-fetch with password_hash (get_current_user strips it)
    full = await db.users.find_one({"id": user["id"]})
    if not full or not verify_password(data.current_password, full.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"password_hash": hash_password(new_pw)}},
    )
    return {"ok": True}


# --- Team members -----------------------------------------------------------
@api.get("/team", response_model=List[TeamMember])
async def list_team(user: dict = Depends(get_current_user)):
    members = await db.team_members.find({}, {"_id": 0}).to_list(1000)
    return members


@api.post("/team", response_model=TeamMember)
async def create_team_member(data: TeamMemberCreate, admin: dict = Depends(require_admin)):
    tm = TeamMember(**data.model_dump())
    await db.team_members.insert_one(tm.model_dump())
    return tm


@api.patch("/team/{member_id}", response_model=TeamMember)
async def update_team_member(member_id: str, data: TeamMemberCreate, admin: dict = Depends(require_admin)):
    await db.team_members.update_one({"id": member_id}, {"$set": data.model_dump()})
    doc = await db.team_members.find_one({"id": member_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return doc


@api.delete("/team/{member_id}")
async def delete_team_member(member_id: str, admin: dict = Depends(require_admin)):
    await db.team_members.delete_one({"id": member_id})
    return {"ok": True}


# --- Metrics ----------------------------------------------------------------
@api.get("/metrics", response_model=List[Metric])
async def list_metrics(user: dict = Depends(get_current_user)):
    metrics = await db.metrics.find({}, {"_id": 0}).sort("order", 1).to_list(1000)
    return metrics


@api.post("/metrics", response_model=Metric)
async def create_metric(data: MetricCreate, admin: dict = Depends(require_admin)):
    count = await db.metrics.count_documents({})
    m = Metric(**data.model_dump(), order=count)
    await db.metrics.insert_one(m.model_dump())
    return m


@api.patch("/metrics/{metric_id}", response_model=Metric)
async def update_metric(metric_id: str, data: MetricUpdate, admin: dict = Depends(require_admin)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        await db.metrics.update_one({"id": metric_id}, {"$set": updates})
    doc = await db.metrics.find_one({"id": metric_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return doc


@api.delete("/metrics/{metric_id}")
async def delete_metric(metric_id: str, admin: dict = Depends(require_admin)):
    await db.metrics.delete_one({"id": metric_id})
    await db.weekly_values.delete_many({"metric_id": metric_id})
    return {"ok": True}


# --- Weekly values ----------------------------------------------------------
@api.get("/scorecard/auto-compute")
async def scorecard_auto_compute(
    week_start: str,
    user: dict = Depends(require_board("weekly_scorecard")),
):
    """
    Auto-compute six derived weekly metrics from external APIs:
      Interviews This Week, Results Received, Hours of Private Tier Calls,
      Testimonial Calls Recorded, Wins Shared, Active Academy Members.

    `week_start` must be an ISO date (e.g. "2026-04-21" — a Monday). Returns
    one block per metric with the computed value and an `explain` string the
    UI can show as a tooltip.
    """
    try:
        ws = datetime.fromisoformat(week_start).date()
    except ValueError:
        raise HTTPException(400, "week_start must be ISO date (YYYY-MM-DD)")
    cache_key = f"scorecard_auto:{ws.isoformat()}"

    async def _compute():
        return await scorecard_auto.auto_compute_all(db, ws)

    return await launches_mod._stale_while_revalidate(
        db, cache_key, ttl_min=60, compute_fn=_compute,
    )


@api.get("/weekly-values")
async def list_weekly_values(user: dict = Depends(get_current_user)):
    values = await db.weekly_values.find({}, {"_id": 0}).to_list(100000)
    return values


@api.post("/weekly-values")
async def upsert_weekly_value(data: WeeklyValueInput, user: dict = Depends(get_current_user)):
    existing = await db.weekly_values.find_one({"metric_id": data.metric_id, "week_start": data.week_start})
    if existing:
        await db.weekly_values.update_one(
            {"metric_id": data.metric_id, "week_start": data.week_start},
            {"$set": {"value": data.value}},
        )
        return {"id": existing["id"], "metric_id": data.metric_id, "week_start": data.week_start, "value": data.value}
    wv = WeeklyValue(metric_id=data.metric_id, week_start=data.week_start, value=data.value)
    await db.weekly_values.insert_one(wv.model_dump())
    return wv.model_dump()


# --- Rocks ------------------------------------------------------------------
@api.get("/rocks", response_model=List[Rock])
async def list_rocks(quarter: Optional[str] = None, user: dict = Depends(get_current_user)):
    q = {"quarter": quarter} if quarter else {}
    rocks = await db.rocks.find(q, {"_id": 0}).to_list(1000)
    return rocks


@api.get("/rocks/quarters")
async def list_quarters(user: dict = Depends(get_current_user)):
    quarters = await db.rocks.distinct("quarter")
    return sorted(quarters, reverse=True)


@api.post("/rocks", response_model=Rock)
async def create_rock(data: RockCreate, admin: dict = Depends(require_admin)):
    r = Rock(**data.model_dump())
    await db.rocks.insert_one(r.model_dump())
    return r


@api.patch("/rocks/{rock_id}", response_model=Rock)
async def update_rock(rock_id: str, data: RockUpdate, user: dict = Depends(get_current_user)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        await db.rocks.update_one({"id": rock_id}, {"$set": updates})
    doc = await db.rocks.find_one({"id": rock_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return doc


@api.delete("/rocks/{rock_id}")
async def delete_rock(rock_id: str, admin: dict = Depends(require_admin)):
    await db.rocks.delete_one({"id": rock_id})
    return {"ok": True}


# --- Launches ---------------------------------------------------------------
@api.get("/launches", response_model=List[Launch])
async def list_launches(user: dict = Depends(get_current_user)):
    launches = await db.launches.find({}, {"_id": 0}).to_list(1000)
    return launches


@api.post("/launches", response_model=Launch)
async def create_launch(data: LaunchCreate, admin: dict = Depends(require_admin)):
    lc = Launch(**data.model_dump())
    await db.launches.insert_one(lc.model_dump())
    # create empty launch_data doc
    ld = LaunchData(launch_id=lc.id)
    await db.launch_data.insert_one(ld.model_dump())
    return lc


@api.delete("/launches/{launch_id}")
async def delete_launch(launch_id: str, admin: dict = Depends(require_admin)):
    await db.launches.delete_one({"id": launch_id})
    await db.launch_data.delete_many({"launch_id": launch_id})
    await db.daily_registrations.delete_many({"launch_id": launch_id})
    return {"ok": True}


@api.patch("/launches/{launch_id}", response_model=Launch)
async def update_launch(launch_id: str, data: LaunchUpdate, admin: dict = Depends(require_admin)):
    updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if updates:
        await db.launches.update_one({"id": launch_id}, {"$set": updates})
    launch = await db.launches.find_one({"id": launch_id}, {"_id": 0})
    if not launch:
        raise HTTPException(404, "Launch not found")
    return launch


@api.get("/launches/{launch_id}/data")
async def get_launch_data(launch_id: str, user: dict = Depends(get_current_user)):
    data = await db.launch_data.find_one({"launch_id": launch_id}, {"_id": 0})
    if not data:
        ld = LaunchData(launch_id=launch_id)
        await db.launch_data.insert_one(ld.model_dump())
        return ld.model_dump()
    return data


@api.patch("/launches/{launch_id}/data")
async def update_launch_data(launch_id: str, data: LaunchDataUpdate, user: dict = Depends(get_current_user)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    existing = await db.launch_data.find_one({"launch_id": launch_id})
    if not existing:
        ld = LaunchData(launch_id=launch_id, **updates)
        await db.launch_data.insert_one(ld.model_dump())
        return ld.model_dump()
    if updates:
        await db.launch_data.update_one({"launch_id": launch_id}, {"$set": updates})
    doc = await db.launch_data.find_one({"launch_id": launch_id}, {"_id": 0})
    return doc


@api.get("/launches/{launch_id}/daily-registrations")
async def list_daily_regs(launch_id: str, user: dict = Depends(get_current_user)):
    regs = await db.daily_registrations.find({"launch_id": launch_id}, {"_id": 0}).sort("date", 1).to_list(10000)
    return regs


@api.post("/daily-registrations")
async def upsert_daily_registration(data: DailyRegistrationInput, user: dict = Depends(get_current_user)):
    existing = await db.daily_registrations.find_one({"launch_id": data.launch_id, "date": data.date})
    if existing:
        await db.daily_registrations.update_one(
            {"launch_id": data.launch_id, "date": data.date},
            {"$set": {"count": data.count}},
        )
        return {"id": existing["id"], **data.model_dump()}
    dr = DailyRegistration(**data.model_dump())
    await db.daily_registrations.insert_one(dr.model_dump())
    return dr.model_dump()


# --- Seed data --------------------------------------------------------------
TEAM_SEED = [
    {"name": "Tessa Davis", "role_title": "Founder", "avatar_url": "https://images.pexels.com/photos/19438566/pexels-photo-19438566.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940"},
    {"name": "Arub Yousuf", "role_title": "Sales & Launches", "avatar_url": "https://images.unsplash.com/photo-1612943705904-e2e101abcd19?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA1NTZ8MHwxfHNlYXJjaHwzfHxwcm9mZXNzaW9uYWwlMjBkb2N0b3IlMjBwb3J0cmFpdHxlbnwwfHx8fDE3NzY2MjU3MzR8MA&ixlib=rb-4.1.0&q=85"},
    {"name": "Oksana Demchenko", "role_title": "Community & Cohort", "avatar_url": None},
    {"name": "Anoop", "role_title": "Head Coach", "avatar_url": "https://images.pexels.com/photos/32160037/pexels-photo-32160037.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940"},
    {"name": "Coralie Fairon", "role_title": "Customer Support", "avatar_url": None},
    {"name": "Alex", "role_title": "Sales Support", "avatar_url": "https://images.unsplash.com/photo-1615177393114-bd2917a4f74a?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA1NTZ8MHwxfHNlYXJjaHwyfHxwcm9mZXNzaW9uYWwlMjBkb2N0b3IlMjBwb3J0cmFpdHxlbnwwfHx8fDE3NzY2MjU3MzR8MA&ixlib=rb-4.1.0&q=85"},
    {"name": "Megan Brockway", "role_title": "Social Media", "avatar_url": None},
]


def _find_member(members, name_substr):
    for m in members:
        if name_substr.lower() in m["name"].lower():
            return m["id"]
    return None


async def _seed_team():
    count = await db.team_members.count_documents({})
    if count > 0:
        return
    for tm in TEAM_SEED:
        doc = TeamMember(**tm).model_dump()
        await db.team_members.insert_one(doc)


async def _seed_metrics():
    count = await db.metrics.count_documents({})
    if count > 0:
        return
    members = await db.team_members.find({}, {"_id": 0}).to_list(1000)
    alex = _find_member(members, "Alex")
    tessa = _find_member(members, "Tessa")
    arub = _find_member(members, "Arub")
    oksana = _find_member(members, "Oksana")
    coralie = _find_member(members, "Coralie")

    metrics_seed = [
        # GROWTH + INTEREST
        {"name": "Podcast Downloads (Audio)", "category": "GROWTH + INTEREST", "owner_ids": [alex, tessa], "goal": 2500, "format": "number"},
        {"name": "Podcast Views (YouTube)", "category": "GROWTH + INTEREST", "owner_ids": [alex, tessa], "goal": 1500, "format": "number"},
        {"name": "EEC Joiners", "category": "GROWTH + INTEREST", "owner_ids": [arub], "goal": 50, "format": "number"},
        {"name": "New (Non-Academy) Community Members", "category": "GROWTH + INTEREST", "owner_ids": [arub], "goal": 30, "format": "number"},
        {"name": "New Email Subscribers", "category": "GROWTH + INTEREST", "owner_ids": [arub], "goal": 200, "format": "number"},
        # CONVERSION + INTENT
        {"name": "People Joined The Waitlist", "category": "CONVERSION + INTENT", "owner_ids": [arub], "goal": 100, "format": "number"},
        {"name": "Email Click-Through Rate (nurture seq.)", "category": "CONVERSION + INTENT", "owner_ids": [arub], "goal": 3.5, "format": "percentage"},
        {"name": "New Signups From The Waitlist", "category": "CONVERSION + INTENT", "owner_ids": [arub], "goal": 20, "format": "number"},
        # REVENUE
        {"name": "New Signup Revenue", "category": "REVENUE", "owner_ids": [arub], "goal": 10000, "format": "currency"},
        {"name": "Upgrade Revenue", "category": "REVENUE", "owner_ids": [arub], "goal": 3000, "format": "currency"},
        {"name": "Refunds", "category": "REVENUE", "owner_ids": [oksana], "goal": 2, "format": "number", "goal_direction": "below"},
        {"name": "Missed Payments", "category": "REVENUE", "owner_ids": [arub, coralie], "goal": 3, "format": "number", "goal_direction": "below"},
        # SOCIAL PROOF
        {"name": "Results Received", "category": "SOCIAL PROOF", "owner_ids": [oksana], "goal": 15, "format": "number"},
        {"name": "Interviews This Week", "category": "SOCIAL PROOF", "owner_ids": [oksana], "goal": 20, "format": "number"},
        {"name": "Testimonial Calls Recorded", "category": "SOCIAL PROOF", "owner_ids": [oksana], "goal": 3, "format": "number"},
        {"name": "Wins Shared", "category": "SOCIAL PROOF", "owner_ids": [oksana], "goal": 10, "format": "number"},
        {"name": "Active Academy Members", "category": "SOCIAL PROOF", "owner_ids": [oksana], "goal": 180, "format": "number"},
        {"name": "Student Satisfaction Score", "category": "SOCIAL PROOF", "owner_ids": [oksana], "goal": 4.5, "format": "number"},
        # DELIVERY + OPERATIONS
        {"name": "Hours Of Private Tier Calls", "category": "DELIVERY + OPERATIONS", "owner_ids": [oksana], "goal": 12, "format": "number"},
    ]
    for i, m in enumerate(metrics_seed):
        doc = Metric(**{k: v for k, v in m.items() if v is not None}, order=i).model_dump()
        # Filter None owner_ids
        doc["owner_ids"] = [o for o in doc["owner_ids"] if o]
        await db.metrics.insert_one(doc)


def _monday_of(d: datetime) -> datetime:
    return d - timedelta(days=d.weekday())


async def _seed_weekly_values():
    count = await db.weekly_values.count_documents({})
    if count > 0:
        return
    import random

    random.seed(42)
    metrics = await db.metrics.find({}, {"_id": 0}).to_list(1000)
    today = datetime.now(timezone.utc)
    monday = _monday_of(today)
    # Seed last 4 full weeks (skip current week so team can fill in)
    for weeks_ago in range(1, 5):
        week_start = (monday - timedelta(weeks=weeks_ago)).date().isoformat()
        for m in metrics:
            goal = m["goal"]
            # Random between 70% and 115% of goal
            factor = random.uniform(0.7, 1.15)
            value = round(goal * factor, 2 if m["format"] in ("currency", "percentage") else 0)
            wv = WeeklyValue(metric_id=m["id"], week_start=week_start, value=value)
            await db.weekly_values.insert_one(wv.model_dump())


async def _seed_rocks():
    count = await db.rocks.count_documents({})
    if count > 0:
        return
    members = await db.team_members.find({}, {"_id": 0}).to_list(1000)
    arub = _find_member(members, "Arub")
    oksana = _find_member(members, "Oksana")
    anoop = _find_member(members, "Anoop")
    coralie = _find_member(members, "Coralie")
    tessa = _find_member(members, "Tessa")

    rocks_seed = [
        # Arub
        (arub, "Deliver APR-26 launch (Good £140k / Better £160k / Best £200k)", "on_track"),
        (arub, "Deliver June launch (target TBD — bonus structure applies)", "on_track"),
        (arub, "Implement Brenna's pre-launch course material", "on_track"),
        (arub, "Develop affiliate programme plan", "off_track"),
        (arub, "Develop & improve the Boost and Go upgrades process", "on_track"),
        # Oksana
        (oksana, "Build & implement a student feedback collection system", "on_track"),
        (oksana, "Systematise tracking & sharing student wins", "on_track"),
        (oksana, "Create standardised private tier onboarding process", "off_track"),
        (oksana, "Build a student progress tracking system across all tiers", "on_track"),
        # Anoop
        (anoop, "Implement coaching peer review process", "on_track"),
        (anoop, "All SIS & RAR student questions answered within 24 hours", "on_track"),
        (anoop, "Establish coaching feedback quality standards", "on_track"),
        (anoop, "Create coach onboarding framework for new hires", "off_track"),
        # Coralie
        (coralie, "Maintain refund rate below 3% for APR-26 and June cohorts", "on_track"),
        (coralie, "Create a process for managing student overwhelm", "on_track"),
        # Tessa
        (tessa, "Build partnerships with training schools", "on_track"),
        (tessa, "Establish EOS quarterly review cadence for the team", "done"),
    ]
    due = "2026-06-30"
    for owner, title, status in rocks_seed:
        if not owner:
            continue
        r = Rock(owner_id=owner, title=title, status=status, due_date=due, notes="", quarter="Q2 2026")
        await db.rocks.insert_one(r.model_dump())


async def _migrate_launches_v2():
    """
    Idempotent migration to AYCI launch phase model v2:
      - 7 phases: in_between_start, early_access, flash_sale, webinar,
        open_cart, close_cart, in_between_end
      - Drops legacy_upgrades, splits in_between into start + end, renames
        early_signups → early_access.
      - Upserts the 4 known launches (NOV-25, FEB-26, APR-26, JUN-26) with
        the canonical phase dates supplied by the team. Existing IDs preserved.
    """
    canonical = [
        {
            "name": "November 2025", "code": "NOV-25",
            "start_date": "2025-10-23", "end_date": "2026-01-14",
            "webinar_date": "2025-11-12",
            "target_good": 120000, "target_better": 140000, "target_best": 170000,
            "phases": {
                "in_between_start": {"start": "2025-10-23T00:00:00Z", "end": "2025-10-30T23:59:59Z"},
                "early_access":     {"start": "2025-10-31T00:00:00Z", "end": "2025-11-10T08:00:00Z"},
                "flash_sale":       {"start": "2025-11-10T08:00:00Z", "end": "2025-11-12T20:00:00Z"},
                "webinar":          {"start": "2025-11-12T20:00:00Z", "end": "2025-11-12T23:59:59Z"},
                "open_cart":        {"start": "2025-11-13T00:00:00Z", "end": "2025-11-18T12:00:00Z"},
                "close_cart":       {"start": "2025-11-18T12:00:00Z", "end": "2025-12-07T23:59:59Z"},
                "in_between_end":   {"start": "2025-12-08T00:00:00Z", "end": "2026-01-14T23:59:59Z"},
            },
        },
        {
            "name": "February 2026", "code": "FEB-26",
            "start_date": "2026-01-15", "end_date": "2026-03-31",
            "webinar_date": "2026-02-04",
            "target_good": 130000, "target_better": 150000, "target_best": 180000,
            "phases": {
                "in_between_start": {"start": "2026-01-15T00:00:00Z", "end": "2026-01-24T23:59:59Z"},
                "early_access":     {"start": "2026-01-25T00:00:00Z", "end": "2026-02-02T08:00:00Z"},
                "flash_sale":       {"start": "2026-02-02T08:00:00Z", "end": "2026-02-04T20:00:00Z"},
                "webinar":          {"start": "2026-02-04T20:00:00Z", "end": "2026-02-04T23:59:59Z"},
                "open_cart":        {"start": "2026-02-05T00:00:00Z", "end": "2026-02-10T12:00:00Z"},
                "close_cart":       {"start": "2026-02-10T12:00:00Z", "end": "2026-03-01T23:59:59Z"},
                "in_between_end":   {"start": "2026-03-02T00:00:00Z", "end": "2026-03-31T23:59:59Z"},
            },
        },
        {
            "name": "April 2026", "code": "APR-26",
            "start_date": "2026-04-01", "end_date": "2026-05-19",
            "webinar_date": "2026-04-22",
            "target_good": 140000, "target_better": 160000, "target_best": 200000,
            "phases": {
                "in_between_start": {"start": "2026-04-01T00:00:00Z", "end": "2026-04-11T23:59:59Z"},
                "early_access":     {"start": "2026-04-12T00:00:00Z", "end": "2026-04-20T08:00:00Z"},
                "flash_sale":       {"start": "2026-04-20T08:00:00Z", "end": "2026-04-22T20:00:00Z"},
                "webinar":          {"start": "2026-04-22T20:00:00Z", "end": "2026-04-22T23:59:59Z"},
                "open_cart":        {"start": "2026-04-23T00:00:00Z", "end": "2026-04-28T12:00:00Z"},
                "close_cart":       {"start": "2026-04-28T12:00:00Z", "end": "2026-05-10T23:59:59Z"},
                "in_between_end":   {"start": "2026-05-11T00:00:00Z", "end": "2026-05-19T23:59:59Z"},
            },
        },
        {
            "name": "June 2026", "code": "JUN-26",
            "start_date": "2026-05-20", "end_date": "2026-08-26",
            "webinar_date": "2026-06-10",
            "target_good": 150000, "target_better": 180000, "target_best": 220000,
            "phases": {
                "in_between_start": {"start": "2026-05-20T00:00:00Z", "end": "2026-05-30T23:59:59Z"},
                "early_access":     {"start": "2026-05-31T00:00:00Z", "end": "2026-06-08T08:00:00Z"},
                "flash_sale":       {"start": "2026-06-08T08:00:00Z", "end": "2026-06-10T20:00:00Z"},
                "webinar":          {"start": "2026-06-10T20:00:00Z", "end": "2026-06-10T23:59:59Z"},
                "open_cart":        {"start": "2026-06-11T00:00:00Z", "end": "2026-06-16T12:00:00Z"},
                "close_cart":       {"start": "2026-06-16T12:00:00Z", "end": "2026-07-05T23:59:59Z"},
                "in_between_end":   {"start": "2026-07-06T00:00:00Z", "end": "2026-08-26T23:59:59Z"},
            },
        },
    ]

    for L in canonical:
        existing = await db.launches.find_one({"code": L["code"]}, {"_id": 0})
        if existing:
            # Replace phases entirely so legacy keys are dropped
            await db.launches.update_one(
                {"code": L["code"]},
                {"$set": {
                    "name": L["name"],
                    "start_date": L["start_date"],
                    "end_date": L["end_date"],
                    "webinar_date": L["webinar_date"],
                    "target_good": L["target_good"],
                    "target_better": L["target_better"],
                    "target_best": L["target_best"],
                    "phases": L["phases"],
                }},
            )
        else:
            new_launch = Launch(
                name=L["name"], code=L["code"],
                start_date=L["start_date"], end_date=L["end_date"],
                webinar_date=L["webinar_date"],
                target_good=L["target_good"],
                target_better=L["target_better"],
                target_best=L["target_best"],
                phases=LaunchPhases(**L["phases"]),
            )
            await db.launches.insert_one(new_launch.model_dump())

    # Bust caches that depend on launch dates
    await db.cache.delete_many({"_id": {"$regex": "^year-overview:"}})
    await db.pace_cache.delete_many({})
    logger.info("[migration] Launches v2 phases applied (4 launches)")


async def _seed_launches():
    count = await db.launches.count_documents({})
    if count > 0:
        return
    launches_seed = [
        {"name": "NOV-25", "start_date": "2025-10-20", "webinar_date": "2025-11-05",
         "target_good": 120000, "target_better": 140000, "target_best": 170000,
         "regs": 1850, "attendance": 42.5,
         "sales": {"academy": 168, "pp": 24, "vip": 9, "boost": 38, "upgrade": 12, "upsell": 22}},
        {"name": "FEB-26", "start_date": "2026-01-20", "webinar_date": "2026-02-05",
         "target_good": 130000, "target_better": 150000, "target_best": 180000,
         "regs": 2120, "attendance": 44.2,
         "sales": {"academy": 186, "pp": 28, "vip": 11, "boost": 44, "upgrade": 15, "upsell": 28}},
        {"name": "APR-26", "start_date": "2026-03-23", "webinar_date": "2026-04-08",
         "target_good": 140000, "target_better": 160000, "target_best": 200000,
         "regs": 1240, "attendance": 0,
         "sales": {"academy": 0, "pp": 0, "vip": 0, "boost": 0, "upgrade": 0, "upsell": 0}},
    ]

    for ls in launches_seed:
        launch = Launch(
            name=ls["name"], start_date=ls["start_date"], webinar_date=ls["webinar_date"],
            target_good=ls["target_good"], target_better=ls["target_better"], target_best=ls["target_best"],
        )
        await db.launches.insert_one(launch.model_dump())
        ld = LaunchData(
            launch_id=launch.id,
            total_registrations=ls["regs"],
            webinar_attendance_rate=ls["attendance"],
            sales_academy_count=ls["sales"]["academy"],
            sales_private_plus_count=ls["sales"]["pp"],
            sales_vip_count=ls["sales"]["vip"],
            sales_boost_count=ls["sales"]["boost"],
            upgrade_count=ls["sales"]["upgrade"],
            upsell_count=ls["sales"]["upsell"],
        )
        await db.launch_data.insert_one(ld.model_dump())

        # Seed daily registrations (~21 days up to webinar)
        import random
        random.seed(hash(ls["name"]) & 0xFFFFFFFF)
        wd = datetime.fromisoformat(ls["webinar_date"])
        total = ls["regs"]
        # distribute with accelerating curve
        day_count = 21
        weights = [max(1, int(i ** 1.8)) for i in range(1, day_count + 1)]
        tw = sum(weights)
        for i, w in enumerate(weights):
            d = wd - timedelta(days=day_count - i)
            count_for_day = round(total * (w / tw))
            dr = DailyRegistration(launch_id=launch.id, date=d.date().isoformat(), count=count_for_day)
            await db.daily_registrations.insert_one(dr.model_dump())


async def _seed_admin():
    admin_email = os.environ["ADMIN_EMAIL"].lower()
    admin_password = os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        doc = {
            "id": str(uuid.uuid4()),
            "email": admin_email,
            "name": "AYCI Admin",
            "role": "admin",
            "board_access": list(ALL_BOARDS),
            "password_hash": hash_password(admin_password),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(doc)
        logger.info(f"Seeded admin user: {admin_email}")
    elif not verify_password(admin_password, existing.get("password_hash", "")):
        await db.users.update_one({"email": admin_email}, {"$set": {"password_hash": hash_password(admin_password)}})
        logger.info(f"Updated admin password: {admin_email}")

    # Backfill: ensure every existing user has a board_access field
    await db.users.update_many(
        {"board_access": {"$exists": False}},
        {"$set": {"board_access": []}},
    )


# --- Scheduler (auto-sync Monday 06:00 Europe/London) -----------------------
scheduler: Optional[AsyncIOScheduler] = None


async def _scheduled_sync() -> None:
    """Runs every Monday at 06:00 Europe/London. Syncs last week's values."""
    try:
        logger.info("[scheduler] Running weekly auto-sync")
        # Last Monday (i.e. the week that just ended — 7 days ago)
        today = datetime.now(timezone.utc).date()
        this_monday = today - timedelta(days=today.weekday())
        last_monday = (this_monday - timedelta(days=7)).isoformat()
        start_dt = datetime.fromisoformat(last_monday + "T00:00:00+00:00")
        end_dt = start_dt + timedelta(days=6, hours=23, minutes=59, seconds=59)
        start_iso = start_dt.isoformat().replace("+00:00", "Z")
        end_iso = end_dt.isoformat().replace("+00:00", "Z")

        metrics = await db.metrics.find({"source_type": {"$ne": None}}, {"_id": 0}).to_list(1000)
        written = 0
        errors: list[str] = []
        for m in metrics:
            source_type = m.get("source_type")
            if not source_type:
                continue
            try:
                value = await connectors.pull_value(source_type, m.get("source_params") or {}, start_iso, end_iso)
                existing = await db.weekly_values.find_one({"metric_id": m["id"], "week_start": last_monday})
                if existing:
                    await db.weekly_values.update_one(
                        {"metric_id": m["id"], "week_start": last_monday},
                        {"$set": {"value": value}},
                    )
                else:
                    await db.weekly_values.insert_one(
                        WeeklyValue(metric_id=m["id"], week_start=last_monday, value=value).model_dump()
                    )
                written += 1
            except Exception as e:
                errors.append(f"{m.get('name')}: {e}")
                logger.warning(f"[scheduler] Sync failed for {m.get('name')}: {e}")
        logger.info(f"[scheduler] Wrote {written} values for w/c {last_monday}; {len(errors)} errors")
    except Exception as e:
        logger.exception(f"[scheduler] Weekly sync crashed: {e}")


# --- Lifecycle --------------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    try:
        await db.users.create_index("email", unique=True)
    except Exception as e:
        logger.warning(f"Index creation warning: {e}")
    await _seed_admin()
    await _seed_team()
    await _seed_metrics()
    await _seed_weekly_values()
    await _seed_rocks()
    await _seed_launches()
    await _migrate_launches_v2()

    # Start weekly auto-sync (Monday 06:00 Europe/London) + daily refreshers
    global scheduler
    tz = os.environ.get("SYNC_TIMEZONE", "Europe/London")
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        _scheduled_sync,
        CronTrigger(day_of_week="mon", hour=6, minute=0, timezone=tz),
        id="weekly_sync",
        replace_existing=True,
    )
    # Daily: refresh Circle member cache at 05:00 (keeps it warm for morning lookups)
    async def _daily_circle_refresh():
        try:
            await db.circle_members_cache.delete_one({"_id": "all"})
            members, _src = await lookup._circle_get_cached_members(db)
            logger.info(f"[daily] Circle cache refreshed: {len(members)} members")
        except Exception as e:
            logger.warning(f"[daily] Circle cache refresh failed: {e}")

    # Daily: invalidate cohort summary cache so next page load re-fetches fresh
    async def _daily_cohort_refresh():
        try:
            await db.cohort_summaries_cache.delete_many({})
            logger.info("[daily] Cohort summary cache cleared")
        except Exception as e:
            logger.warning(f"[daily] Cohort cache clear failed: {e}")

    # Daily: refresh students-at-risk cache (Stripe scan takes a few minutes)
    async def _daily_at_risk_refresh():
        try:
            payload = await at_risk_mod.warm_at_risk_cache(db, force=True)
            logger.info(
                f"[daily] At-risk cache refreshed: {payload.get('total_at_risk', 0)} students at risk"
            )
        except Exception as e:
            logger.warning(f"[daily] At-risk cache refresh failed: {e}")

    # Daily: refresh Tally interview-form cache so coach views are fresh each morning
    async def _daily_tally_refresh():
        try:
            import tally_lookup as tally_mod
            await db.cache.delete_one({"_id": "tally_interviews:nGyGj2"})
            submissions = await tally_mod.get_cached_submissions(db)
            logger.info(f"[daily] Tally interview cache refreshed: {len(submissions)} submissions")
        except Exception as e:
            logger.warning(f"[daily] Tally cache refresh failed: {e}")

    # Daily: refresh phase-breakdown cache for the active launch
    async def _daily_phase_breakdown_refresh():
        try:
            today = datetime.now(timezone.utc).date().isoformat()
            launch = await db.launches.find_one({
                "start_date": {"$lte": today},
                "end_date": {"$gte": today},
            }, {"_id": 0})
            if not launch:
                logger.info("[daily] No active launch — phase-breakdown skip")
                return
            payload = await launches_mod.compute_phase_breakdown(db.launches, launch)
            await db.cache.update_one(
                {"_id": f"phase-breakdown:{launch['id']}"},
                {"$set": {"payload": payload, "cached_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
            logger.info(f"[daily] Phase-breakdown refreshed for {launch['code']}")
        except Exception as e:
            logger.warning(f"[daily] Phase-breakdown refresh failed: {e}")

    scheduler.add_job(
        _daily_circle_refresh,
        CronTrigger(hour=5, minute=0, timezone=tz),
        id="daily_circle_refresh",
        replace_existing=True,
    )
    scheduler.add_job(
        _daily_cohort_refresh,
        CronTrigger(hour=5, minute=5, timezone=tz),
        id="daily_cohort_refresh",
        replace_existing=True,
    )
    scheduler.add_job(
        _daily_at_risk_refresh,
        CronTrigger(hour=5, minute=15, timezone=tz),
        id="daily_at_risk_refresh",
        replace_existing=True,
    )
    scheduler.add_job(
        _daily_tally_refresh,
        CronTrigger(hour=5, minute=20, timezone=tz),
        id="daily_tally_refresh",
        replace_existing=True,
    )
    scheduler.add_job(
        _daily_phase_breakdown_refresh,
        CronTrigger(hour=5, minute=25, timezone=tz),
        id="daily_phase_breakdown_refresh",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"[scheduler] Jobs: weekly_sync (Mon 06:00), daily_circle_refresh (05:00), daily_cohort_refresh (05:05), daily_at_risk_refresh (05:15), daily_tally_refresh (05:20), daily_phase_breakdown_refresh (05:25) — {tz}")

    # Kick off Circle member cache refresh in background (takes ~30-40s for 3.9K members).
    # Fire-and-forget so startup doesn't block.
    import asyncio as _asyncio

    async def _warm_circle_cache():
        try:
            members, source = await lookup._circle_get_cached_members(db)
            logger.info(f"[startup] Circle cache ready: {len(members)} members ({source})")
        except Exception as e:
            logger.warning(f"[startup] Circle cache warm failed: {e}")

    _asyncio.create_task(_warm_circle_cache())

    # Warm at-risk cache in background (depends on Circle cache + Stripe scan,
    # ~3-5 min on first cold run). Skips if cache is fresh.
    async def _warm_at_risk():
        try:
            # Wait a bit so Circle cache warmup gets a head start
            await _asyncio.sleep(30)
            payload = await at_risk_mod.warm_at_risk_cache(db, force=False)
            logger.info(
                f"[startup] At-risk cache ready: {payload.get('total_at_risk', 0)} students at risk"
            )
        except Exception as e:
            logger.warning(f"[startup] At-risk cache warm failed: {e}")

    _asyncio.create_task(_warm_at_risk())

    # Warm phase-breakdown cache for active launch (slow ~5 min cold scan)
    async def _warm_phase_breakdown():
        try:
            await _asyncio.sleep(60)  # let other warmers start first
            today = datetime.now(timezone.utc).date().isoformat()
            launch = await db.launches.find_one({
                "start_date": {"$lte": today},
                "end_date": {"$gte": today},
            }, {"_id": 0})
            if not launch:
                return
            cache_key = f"phase-breakdown:{launch['id']}"
            cached = await db.cache.find_one({"_id": cache_key}, {"_id": 0})
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            if cached and cached.get("cached_at"):
                cached_at = cached["cached_at"]
                if cached_at.tzinfo is None:
                    cached_at = cached_at.replace(tzinfo=timezone.utc)
                if cached_at > cutoff:
                    return  # already fresh
            payload = await launches_mod.compute_phase_breakdown(db.launches, launch)
            await db.cache.update_one(
                {"_id": cache_key},
                {"$set": {"payload": payload, "cached_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
            logger.info(f"[startup] Phase-breakdown ready for {launch['code']}")
        except Exception as e:
            logger.warning(f"[startup] Phase-breakdown warm failed: {e}")

    _asyncio.create_task(_warm_phase_breakdown())

    # Warm cached_fetch_sales + cached_fetch_registrations for the active launch
    # so the first dashboard load is instant.
    async def _warm_active_launch_data():
        try:
            await _asyncio.sleep(15)  # let other warmers start first
            today = datetime.now(timezone.utc).date().isoformat()
            launch = await db.launches.find_one({
                "start_date": {"$lte": today},
                "end_date": {"$gte": today},
            }, {"_id": 0})
            if not launch:
                return
            start_iso = launch["start_date"] + "T00:00:00Z"
            end_iso = launch["end_date"] + "T23:59:59Z"
            await _asyncio.gather(
                launches_mod.cached_fetch_sales(db, start_iso, end_iso),
                launches_mod.cached_fetch_registrations(db, launch["code"], start_iso, end_iso),
                return_exceptions=True,
            )
            logger.info(f"[startup] Active launch sales+regs cache warmed for {launch['code']}")
        except Exception as e:
            logger.warning(f"[startup] Active launch warm failed: {e}")

    _asyncio.create_task(_warm_active_launch_data())


@app.on_event("shutdown")
async def on_shutdown():
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)
    client.close()


# --- Root -------------------------------------------------------------------
@api.get("/")
async def root():
    return {"service": "ayci-team-dashboard", "ok": True}


# --- Sync (external-source pull) -------------------------------------------
def _monday_of_date(iso_date: str) -> str:
    from datetime import date as _date
    y, m, d = [int(x) for x in iso_date.split("-")]
    d_obj = _date(y, m, d)
    delta = d_obj.weekday()
    return (d_obj - timedelta(days=delta)).isoformat()


@api.get("/sync/discover")
async def sync_discover(admin: dict = Depends(require_admin)):
    """Return picker options (shows/tags/spaces/boards) for Settings UI."""
    return await connectors.discover()


@api.get("/sync/connectors")
async def sync_connectors(user: dict = Depends(get_current_user)):
    return sorted(connectors.CONNECTORS.keys())


class SyncRequest(BaseModel):
    week_start: Optional[str] = None  # YYYY-MM-DD (Monday); defaults to last completed week
    overwrite: bool = False           # if True, overwrite existing cell values


@api.post("/sync/run")
async def sync_run(req: SyncRequest, user: dict = Depends(get_current_user)):
    # Compute window (Monday 00:00 → Sunday 23:59 UTC — close enough for weekly metrics)
    if req.week_start:
        week_start = _monday_of_date(req.week_start)
    else:
        # Default: last completed week (this Monday - 7 days)
        today = datetime.now(timezone.utc).date()
        this_monday = today - timedelta(days=today.weekday())
        week_start = (this_monday - timedelta(days=7)).isoformat()
    start_dt = datetime.fromisoformat(week_start + "T00:00:00+00:00")
    end_dt = start_dt + timedelta(days=6, hours=23, minutes=59, seconds=59)
    start_iso = start_dt.isoformat().replace("+00:00", "Z")
    end_iso = end_dt.isoformat().replace("+00:00", "Z")

    metrics = await db.metrics.find({"source_type": {"$ne": None}}, {"_id": 0}).to_list(1000)
    results = []
    for m in metrics:
        source_type = m.get("source_type")
        if not source_type:
            continue
        try:
            value = await connectors.pull_value(
                source_type, m.get("source_params") or {}, start_iso, end_iso
            )
            # upsert respecting overwrite flag
            existing = await db.weekly_values.find_one({"metric_id": m["id"], "week_start": week_start})
            if existing and not req.overwrite:
                results.append({
                    "metric_id": m["id"], "name": m["name"], "value": existing.get("value"),
                    "pulled": value, "written": False, "reason": "existing value preserved",
                })
                continue
            if existing:
                await db.weekly_values.update_one(
                    {"metric_id": m["id"], "week_start": week_start},
                    {"$set": {"value": value}},
                )
            else:
                wv = WeeklyValue(metric_id=m["id"], week_start=week_start, value=value)
                await db.weekly_values.insert_one(wv.model_dump())
            results.append({
                "metric_id": m["id"], "name": m["name"], "value": value, "pulled": value, "written": True,
            })
        except Exception as e:
            logger.warning(f"Sync failed for metric {m.get('name')}: {e}")
            results.append({
                "metric_id": m["id"], "name": m["name"], "error": str(e), "written": False,
            })
    return {
        "week_start": week_start,
        "window": {"start": start_iso, "end": end_iso},
        "total_metrics_with_source": len(metrics),
        "results": results,
    }


# --- Student Lookup --------------------------------------------------------
@api.get("/students/lookup")
async def students_lookup(email: str, user: dict = Depends(require_board("students"))):
    """
    Unified student lookup — fan out an email across Monday.com, Circle,
    Stripe, ConvertKit, and Calendly in parallel. Each platform returns
    independently so partial failures don't block the whole view.
    """
    import asyncio
    import tally_lookup as tally
    if not email or "@" not in email:
        raise HTTPException(400, "Valid email required")
    email = email.strip().lower()
    monday_t, circle_t, stripe_t, ck_t, calendly_t, tally_t = await asyncio.gather(
        lookup.monday_lookup(email),
        lookup.circle_lookup(db, email),
        lookup.stripe_lookup(email),
        lookup.convertkit_lookup(email),
        lookup.calendly_lookup(email),
        tally.lookup_student(db, email),
        return_exceptions=True,
    )

    def _safe(result):
        if isinstance(result, Exception):
            return {"found": False, "data": None, "error": str(result)}
        return result

    monday_safe = _safe(monday_t)
    # Best-effort Drive doc link (only if Monday found a name) — runs in parallel
    # with this final block; uses 24h cache so subsequent calls are sub-50 ms.
    drive_link = None
    student_name = (monday_safe.get("data") or {}).get("name") if monday_safe else None
    if student_name:
        try:
            drive_link = await gdrive.find_student_doc_link(db, student_name)
        except Exception as e:
            drive_link = {"found": False, "error": str(e)}

    return {
        "email": email,
        "monday": monday_safe,
        "circle": _safe(circle_t),
        "stripe": _safe(stripe_t),
        "convertkit": _safe(ck_t),
        "calendly": _safe(calendly_t),
        "tally": _safe(tally_t),
        "drive": drive_link,
    }


@api.get("/students/name-search")
async def students_name_search(
    q: str,
    limit: int = 10,
    user: dict = Depends(require_board("students")),
):
    """Return up to N candidate students matching the name query."""
    return await lookup.name_search(db, q, limit=limit)


@api.post("/students/circle-cache/refresh")
async def circle_cache_refresh(user: dict = Depends(require_board("students"))):
    """Force-refresh the Circle members cache. Returns counts."""
    await db.circle_members_cache.delete_one({"_id": "all"})
    members, source = await lookup._circle_get_cached_members(db)
    return {"refreshed": True, "source": source, "member_count": len(members)}


@api.get("/students/drive-summary")
async def students_drive_summary(
    email: str,
    name: str,
    user: dict = Depends(require_board("students")),
):
    """
    Returns a Claude-generated summary of a student's private-tier Google Doc.
    Cached for 24 h per student email.
    """
    return await gdrive.summarise_student_doc(db, name, email)


@api.get("/students/at-risk")
async def students_at_risk(
    refresh: bool = False,
    user: dict = Depends(require_board("at_risk")),
):
    """
    Returns high-spend Stripe customers (lifetime GBP >= 1000 over the last
    365 days) who are dormant on Circle (>30 days since last_seen_at, or
    never logged in). Cached for 24 h. Pass ?refresh=true to force-recompute
    in the background.
    """
    import asyncio as _asyncio
    if refresh:
        _asyncio.create_task(at_risk_mod.warm_at_risk_cache(db, force=True))
    payload = await at_risk_mod.get_at_risk_cached(db, force=False)
    if payload.get("computing") or payload.get("stale"):
        # Kick off a background warm if the cache is missing/stale and one
        # isn't already running. Worst case the daily scheduler will catch up.
        _asyncio.create_task(at_risk_mod.warm_at_risk_cache(db, force=False))
    return payload




# --- Upcoming Interviews ---------------------------------------------------
@api.get("/interviews/upcoming")
async def upcoming_interviews(
    academy_days: int = 7,
    private_days: int = 14,
    user: dict = Depends(require_board("interviews")),
):
    """
    Returns upcoming interviews grouped by Academy vs private tiers.

    Academy students use the `academy_days` window (default 7). Private /
    Boost & Go tiers use the wider `private_days` window (default 14).
    """
    # Fetch once over the wider window, then trim the academy list client-side.
    wider = max(academy_days, private_days)
    # Cached SWR — first call ~3-4s; subsequent within 30 min are sub-100ms.
    data = await launches_mod._stale_while_revalidate(
        db,
        f"upcoming_interviews:{wider}",
        ttl_min=30,
        compute_fn=lambda: upcoming.fetch_upcoming_interviews(db=db, days=wider),
    )
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    today = _dt.now(_tz.utc).date()
    academy_cutoff = (today + _td(days=academy_days)).isoformat()

    academy = [s for s in data["academy"] if s["interview_date"] <= academy_cutoff]
    return {
        "academy_window": {"days": academy_days, "end": academy_cutoff},
        "private_window": {"days": private_days, "end": data["window"]["end"]},
        "today": today.isoformat(),
        "academy": academy,
        "private": data["private"],
    }


# --- Coach Activity ------------------------------------------------------
@api.get("/coach-activity/summary")
async def coach_activity_summary(
    refresh: bool = False,
    user: dict = Depends(require_board("coach_activity")),
):
    """
    Aggregated coaching engagement across:
      - Circle space "Recorded Answer Review" (since 4 Apr 2026)
      - Circle space "Specific Interview Support" (since 23 Apr 2026)
      - Monday board "AYCI - Private video responses"
    Cached 30 min via stale-while-revalidate.
    """
    if refresh:
        await db["fn_cache"].delete_one({"_id": "coach_activity:summary"})
    return await launches_mod._stale_while_revalidate(
        db,
        "coach_activity:summary",
        ttl_min=30,
        compute_fn=coach_act.fetch_coach_activity_summary,
    )


# --- Cohort --------------------------------------------------------------
@api.get("/cohorts/labels")
async def cohort_labels(user: dict = Depends(require_board("cohort"))):
    """Returns the list of cohort labels from Monday's 'Cohort Joined' dropdown."""
    return await cohort_mod.fetch_cohort_labels()


# --- Launch analytics ----------------------------------------------------
def _launch_window(launch: dict) -> tuple[str, str]:
    start = launch.get("start_date")
    end = launch.get("end_date") or launch.get("webinar_date")
    # normalise to ISO datetime
    def _iso(s: str) -> str:
        if "T" in s:
            return s if s.endswith("Z") else s + "Z" if "+" not in s else s
        return f"{s}T00:00:00Z"
    return _iso(start), _iso(end if "T" in end else end + "T23:59:59")


@api.get("/launches/{launch_id}/registrations")
async def launch_registrations(launch_id: str, user: dict = Depends(get_current_user)):
    """Webinar registrations from Kit, by source + by day, for this launch."""
    launch = await db.launches.find_one({"id": launch_id}, {"_id": 0})
    if not launch:
        raise HTTPException(404, "Launch not found")
    code = launch.get("code")
    if not code:
        raise HTTPException(
            400,
            "Launch has no `code` set. Add the Kit tag prefix code (e.g. APR-26) "
            "in Settings before loading registrations.",
        )
    start, end = _launch_window(launch)
    return await launches_mod.cached_fetch_registrations(db, code, start, end)


@api.get("/launches/{launch_id}/sales")
async def launch_sales(launch_id: str, user: dict = Depends(get_current_user)):
    """Successful Stripe charges within the launch window, daily + by product."""
    launch = await db.launches.find_one({"id": launch_id}, {"_id": 0})
    if not launch:
        raise HTTPException(404, "Launch not found")
    start, end = _launch_window(launch)
    return await launches_mod.cached_fetch_sales(db, start, end)


@api.get("/launches/{launch_id}/onboarding-gap")
async def launch_onboarding_gap(
    launch_id: str,
    refresh: bool = False,
    user: dict = Depends(require_board("launches")),
):
    """
    List of new-signup customers for this launch who are NOT yet in the
    cohort's Circle spaces (per the Monday "On Circle" status). Cached 30 min.
    """
    launch = await db.launches.find_one({"id": launch_id}, {"_id": 0})
    if not launch:
        raise HTTPException(404, "Launch not found")

    cache_key = f"onboarding_gap:{launch_id}"
    if refresh:
        await db["fn_cache"].delete_one({"_id": cache_key})

    async def _compute():
        return await ob_gap.fetch_onboarding_gap(launch)

    return await launches_mod._stale_while_revalidate(
        db, cache_key, ttl_min=30, compute_fn=_compute,
    )


@api.get("/launches/{launch_id}/phase-breakdown")
async def launch_phase_breakdown(
    launch_id: str,
    refresh: bool = False,
    user: dict = Depends(get_current_user),
):
    """Per-phase signups + revenue + registrations for this launch and the
    previous 2 launches. The underlying Stripe scans are slow (3 launches × 1-3 min
    each), so the result is cached in Mongo for 24h and pre-warmed daily at 05:25
    London. Returns `computing: true` while the first warm is in progress.
    """
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    import asyncio as _asyncio
    launch = await db.launches.find_one({"id": launch_id}, {"_id": 0})
    if not launch:
        raise HTTPException(404, "Launch not found")

    cache_key = f"phase-breakdown:{launch_id}"
    cutoff = _dt.now(_tz.utc) - _td(hours=24)
    cached = await db.cache.find_one({"_id": cache_key}, {"_id": 0})
    fresh = False
    if cached and cached.get("cached_at"):
        cached_at = cached["cached_at"]
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=_tz.utc)
        fresh = cached_at > cutoff

    async def _warm():
        try:
            payload = await launches_mod.compute_phase_breakdown(db.launches, launch)
            await db.cache.update_one(
                {"_id": cache_key},
                {"$set": {"payload": payload, "cached_at": _dt.now(_tz.utc)}},
                upsert=True,
            )
        except Exception as e:
            logger.warning(f"[phase-breakdown] Warm failed for {launch_id}: {e}")

    if refresh or not fresh:
        _asyncio.create_task(_warm())

    if cached:
        return {**cached["payload"], "cached": True, "stale": not fresh}

    return {
        "computing": True,
        "current": {"id": launch_id, "code": launch.get("code"),
                    "name": launch.get("name"), "phases": []},
        "previous": [],
        "message": "First-time scan running in the background — refresh in 2-3 minutes.",
    }


@api.get("/launches/{launch_id}/comparison")
async def launch_comparison(
    launch_id: str,
    n_previous: int = 2,
    user: dict = Depends(get_current_user),
):
    """
    Returns registration + sales series for this launch and the N most recent
    previous launches, normalised to day-from-start so charts can overlay them.
    """
    current = await db.launches.find_one({"id": launch_id}, {"_id": 0})
    if not current:
        raise HTTPException(404, "Launch not found")

    all_launches = await db.launches.find({}, {"_id": 0}).sort("start_date", -1).to_list(50)
    # Drop current + only keep launches that started before current
    others = [
        L for L in all_launches
        if L["id"] != launch_id and L.get("start_date", "") < current["start_date"]
        and L.get("code")
    ][:n_previous]

    import asyncio

    async def _series(L: dict) -> dict:
        try:
            start, end = _launch_window(L)
            tasks = []
            tasks.append(launches_mod.cached_fetch_registrations(db, L["code"], start, end))
            tasks.append(launches_mod.cached_fetch_sales(db, start, end))
            regs, sales = await asyncio.gather(*tasks, return_exceptions=True)
            return {
                "id": L["id"],
                "name": L["name"],
                "code": L.get("code"),
                "start_date": L["start_date"],
                "registrations": regs if not isinstance(regs, Exception) else None,
                "sales": sales if not isinstance(sales, Exception) else None,
                "registrations_aligned": (
                    launches_mod.align_by_day_offset(regs.get("by_day", []), start)
                    if not isinstance(regs, Exception) else []
                ),
                "sales_aligned": (
                    launches_mod.align_by_day_offset(sales.get("by_day", []), start)
                    if not isinstance(sales, Exception) else []
                ),
            }
        except Exception as e:
            return {"id": L["id"], "name": L["name"], "error": str(e)}

    series = await asyncio.gather(*[_series(L) for L in [current] + others])
    return {
        "current": series[0],
        "previous": series[1:],
    }


@api.get("/launches/year-overview")
async def launches_year_overview(user: dict = Depends(get_current_user)):
    """
    Returns all launches with their date ranges + total Stripe revenue,
    plus a 'today' marker. Cached for 1 hour. Used to render the year-strip
    timeline at the top of the Launch Dashboard.
    """
    from datetime import datetime, timezone, timedelta
    today_iso = datetime.now(timezone.utc).date().isoformat()
    cache_key = f"year-overview:{today_iso}"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    cached = await db.pace_cache.find_one({"_id": cache_key}, {"_id": 0})
    if cached and cached.get("cached_at"):
        c_at = cached["cached_at"]
        if c_at.tzinfo is None:
            c_at = c_at.replace(tzinfo=timezone.utc)
        if c_at > cutoff:
            return {**cached["payload"], "cached": True}

    all_launches = await db.launches.find({}, {"_id": 0}).sort("start_date", 1).to_list(50)
    import asyncio

    async def _enrich(L: dict) -> dict:
        if not L.get("start_date") or not L.get("end_date"):
            return {**L, "revenue_gbp": 0, "sales_count": 0, "is_active": False, "is_future": False}
        try:
            sales = await launches_mod.cached_fetch_sales(
                db,
                L["start_date"] + "T00:00:00Z",
                L["end_date"] + "T23:59:59Z",
            )
            revenue = sales.get("total_amount_gbp", 0)
            count = sales.get("total_count", 0)
        except Exception:
            revenue, count = 0, 0
        is_active = L["start_date"] <= today_iso <= L["end_date"]
        is_future = L["start_date"] > today_iso
        is_past = L["end_date"] < today_iso
        return {
            "id": L["id"],
            "name": L["name"],
            "code": L.get("code"),
            "start_date": L["start_date"],
            "end_date": L["end_date"],
            "webinar_date": L.get("webinar_date"),
            "target_good": L.get("target_good"),
            "target_better": L.get("target_better"),
            "target_best": L.get("target_best"),
            "revenue_gbp": revenue,
            "sales_count": count,
            "is_active": is_active,
            "is_future": is_future,
            "is_past": is_past,
        }

    enriched = await asyncio.gather(*[_enrich(L) for L in all_launches])
    payload = {"today": today_iso, "launches": enriched}
    await db.pace_cache.update_one(
        {"_id": cache_key},
        {"$set": {"payload": payload, "cached_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return {**payload, "cached": False}


@api.get("/launches/active/pace")
async def active_launch_pace(user: dict = Depends(get_current_user)):
    """
    Returns the pace for the launch that's currently in progress (today is
    between its start_date and end_date). Cached in Mongo for 1 hour to
    keep the dashboard snappy (computation involves multiple Stripe pulls).
    """
    from datetime import datetime, timezone, timedelta

    today_iso = datetime.now(timezone.utc).date().isoformat()
    active = await db.launches.find_one(
        {"start_date": {"$lte": today_iso}, "end_date": {"$gte": today_iso}}, {"_id": 0}
    )
    if not active:
        return {"active": False, "message": "No active launch"}

    cache_key = f"pace:{active['id']}:{today_iso}"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    cached = await db.pace_cache.find_one({"_id": cache_key}, {"_id": 0})
    if cached and cached.get("cached_at") and (
        cached["cached_at"].replace(tzinfo=timezone.utc) if cached["cached_at"].tzinfo is None else cached["cached_at"]
    ) > cutoff:
        return {**cached["payload"], "cached": True}

    all_launches = await db.launches.find({}, {"_id": 0}).sort("start_date", -1).to_list(50)
    previous = [
        L for L in all_launches
        if L["id"] != active["id"] and L.get("start_date", "") < active["start_date"]
    ][:3]
    pace = await launches_mod.compute_pace(db, active, previous)
    pace["active"] = True
    pace["launch_id"] = active["id"]
    pace["launch_name"] = active["name"]
    pace["webinar_date"] = active.get("webinar_date")

    await db.pace_cache.update_one(
        {"_id": cache_key},
        {"$set": {"payload": pace, "cached_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return {**pace, "cached": False}


@api.get("/launches/{launch_id}/pace")
async def launch_pace(launch_id: str, user: dict = Depends(get_current_user)):
    """
    Forecast where the launch will land by close, based on previous-launch ratios.
    """
    current = await db.launches.find_one({"id": launch_id}, {"_id": 0})
    if not current:
        raise HTTPException(404, "Launch not found")

    all_launches = await db.launches.find({}, {"_id": 0}).sort("start_date", -1).to_list(50)
    previous = [
        L for L in all_launches
        if L["id"] != launch_id and L.get("start_date", "") < current["start_date"]
    ][:3]
    return await launches_mod.compute_pace(db, current, previous)


@api.get("/cohorts/summary")
async def cohort_summary_endpoint(
    cohort: str = "April 26",
    circle_tag: Optional[str] = None,
    new_tag_id: Optional[int] = None,
    legacy_tag_id: Optional[int] = None,
    intros_space_id: Optional[int] = None,
    user: dict = Depends(require_board("cohort")),
):
    """
    Aggregated cohort stats. New / Legacy counts come from ConvertKit tags
    (authoritative). Circle cross-reference uses the cached members list.
    """
    return await cohort_mod.cohort_summary(
        db,
        cohort,
        circle_tag=circle_tag,
        new_tag_id=new_tag_id,
        legacy_tag_id=legacy_tag_id,
        intros_space_id=intros_space_id,
    )


app.include_router(api)

_cors_origins_raw = os.environ.get("CORS_ORIGINS", "").strip()
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
if not _cors_origins:
    logger.warning(
        "[cors] CORS_ORIGINS env var is empty — no cross-origin requests will be allowed."
    )

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
