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
import cohort as cohort_mod
import google_drive as gdrive
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


# --- Models -----------------------------------------------------------------
class LoginInput(BaseModel):
    email: EmailStr
    password: str


class RegisterInput(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: Literal["admin", "user"] = "user"


class UserOut(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: str


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
    goal: float = 0
    format: MetricFormat = "number"
    order: int = 0
    goal_direction: Literal["above", "below"] = "above"
    source_type: Optional[str] = None  # e.g. "convertkit_tag_new_subscribers"
    source_params: Optional[dict] = None  # connector-specific config


class MetricCreate(BaseModel):
    name: str
    category: MetricCategory
    owner_ids: List[str] = []
    goal: float = 0
    format: MetricFormat = "number"
    goal_direction: Literal["above", "below"] = "above"
    source_type: Optional[str] = None
    source_params: Optional[dict] = None


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


class Launch(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str  # e.g. "APR-26"
    start_date: str
    webinar_date: str
    target_good: float
    target_better: float
    target_best: float


class LaunchCreate(BaseModel):
    name: str
    start_date: str
    webinar_date: str
    target_good: float
    target_better: float
    target_best: float


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
    return {"id": user["id"], "email": user["email"], "name": user["name"], "role": user.get("role", "user")}


@api.post("/auth/register")
async def register(data: RegisterInput, response: Response, admin: dict = Depends(require_admin)):
    email = data.email.lower()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user_doc = {
        "id": str(uuid.uuid4()),
        "email": email,
        "name": data.name,
        "role": data.role,
        "password_hash": hash_password(data.password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(user_doc)
    return {"id": user_doc["id"], "email": email, "name": data.name, "role": data.role}


@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return user


@api.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
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
            "password_hash": hash_password(admin_password),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(doc)
        logger.info(f"Seeded admin user: {admin_email}")
    elif not verify_password(admin_password, existing.get("password_hash", "")):
        await db.users.update_one({"email": admin_email}, {"$set": {"password_hash": hash_password(admin_password)}})
        logger.info(f"Updated admin password: {admin_email}")


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

    # Start weekly auto-sync (Monday 06:00 Europe/London)
    global scheduler
    tz = os.environ.get("SYNC_TIMEZONE", "Europe/London")
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        _scheduled_sync,
        CronTrigger(day_of_week="mon", hour=6, minute=0, timezone=tz),
        id="weekly_sync",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"[scheduler] Auto-sync scheduled: Mondays 06:00 {tz}")

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
async def students_lookup(email: str, user: dict = Depends(get_current_user)):
    """
    Unified student lookup — fan out an email across Monday.com, Circle,
    Stripe, ConvertKit, and Calendly in parallel. Each platform returns
    independently so partial failures don't block the whole view.
    """
    import asyncio
    if not email or "@" not in email:
        raise HTTPException(400, "Valid email required")
    email = email.strip().lower()
    monday_t, circle_t, stripe_t, ck_t, calendly_t = await asyncio.gather(
        lookup.monday_lookup(email),
        lookup.circle_lookup(db, email),
        lookup.stripe_lookup(email),
        lookup.convertkit_lookup(email),
        lookup.calendly_lookup(email),
        return_exceptions=True,
    )

    def _safe(result):
        if isinstance(result, Exception):
            return {"found": False, "data": None, "error": str(result)}
        return result

    return {
        "email": email,
        "monday": _safe(monday_t),
        "circle": _safe(circle_t),
        "stripe": _safe(stripe_t),
        "convertkit": _safe(ck_t),
        "calendly": _safe(calendly_t),
    }


@api.post("/students/circle-cache/refresh")
async def circle_cache_refresh(user: dict = Depends(get_current_user)):
    """Force-refresh the Circle members cache. Returns counts."""
    await db.circle_members_cache.delete_one({"_id": "all"})
    members, source = await lookup._circle_get_cached_members(db)
    return {"refreshed": True, "source": source, "member_count": len(members)}


@api.get("/students/drive-summary")
async def students_drive_summary(
    email: str,
    name: str,
    user: dict = Depends(get_current_user),
):
    """
    Returns a Claude-generated summary of a student's private-tier Google Doc.
    Cached for 24 h per student email.
    """
    return await gdrive.summarise_student_doc(db, name, email)


# --- Upcoming Interviews ---------------------------------------------------
@api.get("/interviews/upcoming")
async def upcoming_interviews(
    academy_days: int = 7,
    private_days: int = 14,
    user: dict = Depends(get_current_user),
):
    """
    Returns upcoming interviews grouped by Academy vs private tiers.

    Academy students use the `academy_days` window (default 7). Private /
    Boost & Go tiers use the wider `private_days` window (default 14).
    """
    # Fetch once over the wider window, then trim the academy list client-side.
    wider = max(academy_days, private_days)
    data = await upcoming.fetch_upcoming_interviews(days=wider)
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


# --- Cohort --------------------------------------------------------------
@api.get("/cohorts/summary")
async def cohort_summary_endpoint(
    cohort: str = "April 26",
    circle_tag: Optional[str] = None,
    new_tag_id: Optional[int] = None,
    legacy_tag_id: Optional[int] = None,
    intros_space_id: Optional[int] = None,
    user: dict = Depends(get_current_user),
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

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
