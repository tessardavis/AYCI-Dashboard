from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import connectors
import student_lookup as lookup
import upcoming_interviews as upcoming
import coach_activity as coach_act
import onboarding_gap as ob_gap
import scorecard_auto
import settings_store
import cohort as cohort_mod
import google_drive as gdrive
import launches as launches_mod
import at_risk as at_risk_mod
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# --- Shared infrastructure --------------------------------------------------
from db import client, db
from auth_utils import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, set_auth_cookies,
)
from deps import (
    ALL_BOARDS, ADMIN_ONLY_BOARDS,
    get_current_user, require_admin, require_board, user_has_board,
)
from models import (
    LoginInput, RegisterInput, UserOut, UserPatch, ChangePasswordInput,
    TeamMember, TeamMemberCreate,
    Metric, MetricCreate, MetricUpdate,
    WeeklyValue, WeeklyValueInput,
    Rock, RockCreate, RockUpdate,
    LaunchPhase, LaunchPhases,
    Launch, LaunchCreate, LaunchUpdate,
    LaunchData, LaunchDataUpdate,
    DailyRegistration, DailyRegistrationInput,
)

# --- App --------------------------------------------------------------------
app = FastAPI(title="AYCI Team Dashboard")
api = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Keep strong references to long-running asyncio tasks so the GC can't kill
# them mid-flight. Holds the Circle DM polling loop task (and any other
# fire-and-forget background loops we add later).
_INDEPENDENT_POLLER_TASKS: list = []


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
        "team_member_id": user.get("team_member_id"),
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
    for u in users:
        u["board_access"] = u.get("board_access") or []
    team_members = await db.team_members.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
    return {
        "users": users,
        "all_boards": ALL_BOARDS,
        "team_members": team_members,
    }


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
    # team_member_id: "" or None means "unlink"; a real ID links.
    if data.team_member_id is not None:
        tm_id = (data.team_member_id or "").strip() or None
        if tm_id:
            exists = await db.team_members.find_one({"id": tm_id}, {"_id": 1})
            if not exists:
                raise HTTPException(status_code=400, detail="Unknown team_member_id")
        update["team_member_id"] = tm_id
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


# --- App Settings: Cohort Milestones ---------------------------------------
@api.get("/settings/cohort-milestones")
async def get_cohort_milestones(user: dict = Depends(get_current_user)):
    """Return the 5 milestone tag names tracked for cohort engagement.
    Available to any logged-in user (used by Student Lookup engagement bar)."""
    milestones = await settings_store.get_cohort_milestones(db)
    return {"milestones": milestones}


@api.put("/settings/cohort-milestones")
async def update_cohort_milestones(
    payload: dict,
    admin: dict = Depends(require_admin),
):
    """Admin-only: replace the 5 cohort milestone tag names."""
    milestones = payload.get("milestones")
    try:
        saved = await settings_store.set_cohort_milestones(db, milestones)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"milestones": saved}


@api.get("/settings/coach-spaces")
async def get_coach_spaces_endpoint(user: dict = Depends(get_current_user)):
    """Current Coach Activity Circle space IDs + cohort start dates.
    Available to anyone with auth (read-only for non-admins)."""
    return await settings_store.get_coach_spaces(db)


@api.put("/settings/coach-spaces")
async def update_coach_spaces_endpoint(
    payload: dict,
    admin: dict = Depends(require_admin),
):
    """Admin-only: update Coach Activity Circle space IDs / cohort start dates.
    Accepts any subset of: recorded_answer_space_id, interview_support_space_id,
    recorded_answer_start, interview_support_start. Clears the SWR cache so the
    next dashboard load shows the new space immediately."""
    try:
        saved = await settings_store.set_coach_spaces(db, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Bust the cached coach-activity payload so the change takes effect now.
    await db["fn_cache"].delete_one({"_id": "coach_activity:summary"})
    return saved


@api.post("/coach-activity/circle-video-alerts/test")
async def test_circle_video_alerts(admin: dict = Depends(require_admin)):
    """Admin-only: force a re-scan of the Recorded Answer Review space and
    post any new (member, week) over-3 alerts to #circle-days right now."""
    import circle_video_alerts as cva
    return await cva.check_and_send(db)


class CircleDaysWebhookPayload(BaseModel):
    url: str = ""


@api.get("/coach-activity/circle-video-alerts/webhook")
async def get_circle_days_webhook(admin: dict = Depends(require_admin)):
    """Returns whether the #circle-days webhook is configured + a masked preview."""
    import circle_video_alerts as cva
    url = await cva.get_webhook_url(db)
    return {
        "configured": bool(url),
        "masked": (url[:36] + "…" + url[-6:]) if url and len(url) > 50 else (url or ""),
    }


@api.post("/coach-activity/circle-video-alerts/webhook")
async def set_circle_days_webhook(
    body: CircleDaysWebhookPayload,
    admin: dict = Depends(require_admin),
):
    """Store the #circle-days Slack webhook URL in MongoDB so the alert works
    on production without needing an env-var redeploy. Pass empty string to
    clear."""
    import circle_video_alerts as cva
    return await cva.set_webhook_url(db, body.url)


# -------------------------- Slack bot DM (assignee notifications) ----------
class SlackBotTokenPayload(BaseModel):
    value: str = ""


class SlackTestDmPayload(BaseModel):
    email: str
    text: str = ":wave: Test DM from AYCI Dashboard — your Slack bot integration is wired correctly."


@api.get("/slack/bot-token")
async def get_slack_bot_token(admin: dict = Depends(require_admin)):
    import slack_dm
    val = await slack_dm.get_bot_token(db)
    return {
        "configured": bool(val),
        "masked": (val[:8] + "…" + val[-4:]) if val else "",
    }


@api.post("/slack/bot-token")
async def set_slack_bot_token(
    body: SlackBotTokenPayload,
    admin: dict = Depends(require_admin),
):
    """Save the Slack bot token (xoxb-...) to MongoDB. Pass empty to clear."""
    import slack_dm
    return await slack_dm.set_bot_token(db, body.value)


@api.post("/slack/test-dm")
async def slack_test_dm(
    body: SlackTestDmPayload,
    admin: dict = Depends(require_admin),
):
    """Verify the bot token + user lookup work by DMing the supplied email."""
    import slack_dm
    return await slack_dm.dm_user(db, body.email, body.text)


@api.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"ok": True}


@api.post("/auth/refresh")
async def refresh_token(request: Request, response: Response):
    """Mint a fresh access_token (and rotate the refresh_token) using the
    httpOnly refresh cookie. Returns the user payload so the client can
    keep its in-memory state in sync without a follow-up /auth/me call."""
    import jwt as _jwt
    from auth_utils import jwt_secret as _secret, JWT_ALGORITHM as _alg
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = _jwt.decode(token, _secret(), algorithms=[_alg])
    except _jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")
    user = await db.users.find_one(
        {"id": payload["sub"]}, {"_id": 0, "password_hash": 0}
    )
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    access = create_access_token(user["id"], user["email"], user.get("role", "user"))
    new_refresh = create_refresh_token(user["id"])
    set_auth_cookies(response, access, new_refresh)
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user.get("role", "user"),
        "team_member_id": user.get("team_member_id"),
        "board_access": (
            ALL_BOARDS + ADMIN_ONLY_BOARDS
            if user.get("role") == "admin"
            else (user.get("board_access") or [])
        ),
    }


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


async def _ensure_results_from_this_weeks_metric():
    """Idempotent: insert 'Results From This Week's Interviews' metric if it
    doesn't already exist. Added Apr-29-2026 alongside the new auto-compute
    function. Owner: Oksana (matches the related 'Results Received' metric)."""
    name = "Results From This Week's Interviews"
    if await db.metrics.find_one({"name": name}, {"_id": 1}):
        return
    members = await db.team_members.find({}, {"_id": 0}).to_list(1000)
    oksana = _find_member(members, "Oksana")
    last_order = await db.metrics.find_one(
        {"category": "SOCIAL PROOF"}, sort=[("order", -1)], projection={"_id": 0, "order": 1},
    )
    order = (last_order or {}).get("order", 0) + 1
    doc = Metric(
        name=name,
        category="SOCIAL PROOF",
        owner_ids=[oksana] if oksana else [],
        goal=80,
        format="percentage",
        order=order,
    ).model_dump()
    doc["owner_ids"] = [o for o in doc["owner_ids"] if o]
    await db.metrics.insert_one(doc)
    logger.info(f"[migration] Inserted metric '{name}' (id={doc['id']})")


async def _backfill_results_received_goal():
    """One-shot fix: 'Results Received' metric was originally seeded as a count
    (goal=15) but later converted to a percentage; goal was wiped to None during
    that conversion. Restore a sensible 50% baseline (responsiveness target —
    half of this week's interviewees report back the same week)."""
    metric = await db.metrics.find_one(
        {"name": "Results Received"}, {"_id": 0, "id": 1, "goal": 1, "format": 1},
    )
    if not metric:
        return
    if metric.get("goal") is not None:
        return
    if metric.get("format") != "percentage":
        return
    await db.metrics.update_one(
        {"id": metric["id"]},
        {"$set": {"goal": 50.0}},
    )
    logger.info("[migration] Backfilled 'Results Received' goal → 50%")


async def _ensure_becky_team_member():
    """Idempotent: ensure a `team_members` row exists for Becky Platt and that
    her user is linked to it. Becky was the only post-launch team user without
    a matching team_member when the auto-link migration ran on 29 Apr 2026."""
    user = await db.users.find_one(
        {"email": "becky@medicalinterviewprep.com"},
        {"_id": 0, "id": 1, "team_member_id": 1, "name": 1},
    )
    if not user:
        return
    tm = await db.team_members.find_one({"name": "Becky Platt"}, {"_id": 0, "id": 1})
    if not tm:
        tm_doc = TeamMember(name="Becky Platt", role_title="Coach").model_dump()
        await db.team_members.insert_one(tm_doc)
        tm = {"id": tm_doc["id"]}
        logger.info("[migration] Inserted team_member 'Becky Platt'")
    if user.get("team_member_id") != tm["id"]:
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"team_member_id": tm["id"]}},
        )
        logger.info(
            "[migration] Linked user 'Becky Platt' → team_member 'Becky Platt'"
        )



async def _autolink_users_to_team_members():
    """Idempotent: link `users` to `team_members` by name (case-insensitive
    substring) when `team_member_id` is missing. Logs each match. Users we
    can't auto-match keep team_member_id=None and an admin can set it later
    via Admin → Users."""
    users = await db.users.find(
        {"$or": [
            {"team_member_id": {"$exists": False}},
            {"team_member_id": None},
        ]},
        {"_id": 0, "id": 1, "name": 1, "email": 1},
    ).to_list(1000)
    members = await db.team_members.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)
    if not users or not members:
        return

    def _norm(s):
        return (s or "").strip().lower()

    for u in users:
        u_name = _norm(u.get("name"))
        if not u_name:
            continue
        # 1. exact match
        match = next((m for m in members if _norm(m["name"]) == u_name), None)
        # 2. substring either direction (e.g. "Anoop Chidambaram" user vs "Anoop" team_member)
        if not match:
            match = next(
                (
                    m for m in members
                    if _norm(m["name"]) and (_norm(m["name"]) in u_name or u_name in _norm(m["name"]))
                ),
                None,
            )
        if match:
            await db.users.update_one(
                {"id": u["id"]},
                {"$set": {"team_member_id": match["id"]}},
            )
            logger.info(
                f"[migration] Linked user '{u.get('name')}' → team_member '{match['name']}'"
            )


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

        # Auto-fill the 6 derived metrics (Calendly/Circle/Tally/Monday-derived)
        try:
            ws = datetime.fromisoformat(last_monday).date()
            auto = await scorecard_auto.auto_compute_all(db, ws)
            metrics_by_name = {m["name"].lower(): m for m in await db.metrics.find({}, {"_id": 0}).to_list(1000)}
            auto_written = 0
            for name, payload in (auto.get("metrics") or {}).items():
                v = payload.get("value")
                if v is None or payload.get("error"):
                    continue
                metric = metrics_by_name.get(name.lower())
                if not metric:
                    continue
                await db.weekly_values.update_one(
                    {"metric_id": metric["id"], "week_start": last_monday},
                    {"$set": {"metric_id": metric["id"], "week_start": last_monday, "value": float(v)}},
                    upsert=True,
                )
                auto_written += 1
            logger.info(f"[scheduler] Auto-fill wrote {auto_written} derived metrics for w/c {last_monday}")
        except Exception as e:
            logger.exception(f"[scheduler] Auto-fill failed: {e}")
    except Exception as e:
        logger.exception(f"[scheduler] Weekly sync crashed: {e}")


# --- Lifecycle --------------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    try:
        await db.users.create_index("email", unique=True)
        # Without this compound index every Cohort Leaderboard request
        # COLLSCANs 34K+ snapshot rows; combined with 4× redundant calls to
        # get_top_leaderboard that pushed the endpoint past the 30s frontend
        # timeout and rendered the page empty.
        await db.leaderboard_snapshots.create_index(
            [("cohort", 1), ("snapshot_date", -1)],
            name="cohort_snapshot_date",
        )
    except Exception as e:
        logger.warning(f"Index creation warning: {e}")
    await _seed_admin()
    await _seed_team()
    await _seed_metrics()
    await _ensure_results_from_this_weeks_metric()
    await _backfill_results_received_goal()
    await _autolink_users_to_team_members()
    await _ensure_becky_team_member()
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

    async def _daily_sla_digest():
        import sla_notifications
        try:
            await sla_notifications.send_sla_digest(db)
        except Exception as e:
            logger.warning(f"[scheduler] SLA digest failed: {e}")

    scheduler.add_job(
        _daily_sla_digest,
        CronTrigger(hour=8, minute=0, timezone=tz),
        id="daily_sla_digest",
        replace_existing=True,
        max_instances=1, coalesce=True,
    )

    async def _spotlight_reminders_tick():
        import spotlight_slack
        try:
            await spotlight_slack.check_and_send_reminders(db)
        except Exception as e:
            logger.warning(f"[scheduler] spotlight reminders failed: {e}")

    scheduler.add_job(
        _spotlight_reminders_tick,
        CronTrigger(minute="*/5", timezone=tz),
        id="spotlight_reminders",
        replace_existing=True,
        max_instances=1, coalesce=True,
    )

    async def _hourly_prewarm_upcoming_calls():
        # Pre-fetch Drive doc summaries for every student with a Calendly
        # call in the next 36h, so when the team opens Student Lookup
        # right before the call the AI summary renders instantly.
        import upcoming_call_prewarm
        try:
            res = await upcoming_call_prewarm.prewarm_upcoming_calls(db)
            logger.info(f"[scheduler] prewarm upcoming calls: {res}")
        except Exception as e:
            logger.warning(f"[scheduler] prewarm upcoming calls failed: {e}")

    scheduler.add_job(
        _hourly_prewarm_upcoming_calls,
        CronTrigger(minute=5, timezone=tz),
        id="prewarm_upcoming_calls",
        replace_existing=True,
    )
    # Fire once shortly after startup so we don't wait an hour on first deploy
    from zoneinfo import ZoneInfo
    scheduler.add_job(
        _hourly_prewarm_upcoming_calls,
        "date",
        run_date=datetime.now(ZoneInfo(tz)) + timedelta(seconds=60),
        id="prewarm_upcoming_calls_initial",
        replace_existing=True,
    )

    async def _daily_leaderboard_snapshot():
        import leaderboard_snapshots
        try:
            result = await leaderboard_snapshots.snapshot_all_active_cohorts(db)
            logger.info(f"[scheduler] leaderboard snapshot: {result}")
        except Exception as e:
            logger.warning(f"[scheduler] leaderboard snapshot failed: {e}")

    scheduler.add_job(
        _daily_leaderboard_snapshot,
        CronTrigger(hour=2, minute=15, timezone=tz),
        id="daily_leaderboard_snapshot",
        replace_existing=True,
    )

    # Periodic Tally → Tickets sync (every 15 min). The webhook delivers most
    # tickets in real time; this poll is a safety net for missed webhook calls
    # and also serves as the initial backfill on first deploy.
    async def _tickets_tally_sync():
        import tickets as tickets_mod
        try:
            res = await tickets_mod.sync_tally(db)
            if res.get("inserted"):
                logger.info(f"[scheduler] tickets tally sync: {res}")
        except Exception as e:
            logger.warning(f"[scheduler] tickets tally sync failed: {e}")

    scheduler.add_job(
        _tickets_tally_sync,
        CronTrigger(minute="*/15", timezone=tz),
        id="tickets_tally_sync",
        replace_existing=True,
    )

    # Periodic Wati → Tickets reconcile (every 5 min). Belt-and-braces against
    # webhook drops or webhook-URL drift between preview/production. Polls
    # /api/v1/getMessages/{wa} for every open WhatsApp ticket and appends any
    # inbound messages that aren't already on the ticket.
    async def _wati_reconcile():
        import wati as wati_mod
        try:
            res = await wati_mod.reconcile_open_tickets(db)
            if res.get("appended"):
                logger.info(f"[scheduler] wati reconcile: {res}")
        except Exception as e:
            logger.warning(f"[scheduler] wati reconcile failed: {e}")

    scheduler.add_job(
        _wati_reconcile,
        CronTrigger(minute="*/5", timezone=tz),
        id="wati_reconcile",
        replace_existing=True,
    )

    # Circle Recorded-Answer-Review video-spam alerts → #circle-days Slack.
    # Fires the moment a student crosses 3 posts in the current calendar week
    # (Mon-Sun UK). Idempotent per (member, week) via `circle_video_alerts_sent`.
    async def _circle_video_alerts():
        import circle_video_alerts as cva
        try:
            res = await cva.check_and_send(db)
            if res.get("sent"):
                logger.info(f"[scheduler] circle video alerts: {res}")
        except Exception as e:
            logger.warning(f"[scheduler] circle video alerts failed: {e}")

    scheduler.add_job(
        _circle_video_alerts,
        CronTrigger(minute="*/5", timezone=tz),
        id="circle_video_alerts",
        replace_existing=True,
        max_instances=1, coalesce=True,
    )

    # Over-allowance booking detector (every 5 min). For every Private Plus /
    # VIP student on Monday, compare all-time Calendly private-call count
    # against Monday's total slot allowance. Slack-DMs Oksana the first time
    # a student goes over, and re-DMs only when `over_by` grows further.
    async def _over_allowance_check():
        import over_allowance_alerts as oaa
        try:
            res = await oaa.notify_over_allowance_breaches(db)
            if res.get("notified"):
                logger.info(f"[scheduler] over-allowance: {res}")
        except Exception as e:
            logger.warning(f"[scheduler] over-allowance check failed: {e}")

    scheduler.add_job(
        _over_allowance_check,
        CronTrigger(minute="*/5", timezone=tz),
        id="over_allowance_check",
        replace_existing=True,
    )

    # Gmail → Tickets sync every 15 min for every connected inbox. Skips
    # silently if GOOGLE_CLIENT_ID/SECRET aren't set (i.e. integration not
    # yet configured) — no inboxes possible.
    async def _gmail_inbox_sync():
        import gmail_sync
        try:
            res = await gmail_sync.sync_all(db)
            if res.get("created") or res.get("updated") or res.get("errors"):
                logger.info(f"[scheduler] gmail sync: {res}")
        except Exception as e:
            logger.warning(f"[scheduler] gmail sync failed: {e}")

    scheduler.add_job(
        _gmail_inbox_sync,
        CronTrigger(minute="*/15", timezone=tz),
        id="gmail_inbox_sync",
        replace_existing=True,
    )

    # Circle DM Bot polling — every 1 minute, for each enabled coach admin,
    # checks their DM threads via Headless API and replies / escalates.
    # Defaults to ENABLED. Preview's /app/backend/.env sets
    # CIRCLE_BOT_ENABLED=false so preview and production don't both poll the
    # same Circle inbox and race each other into human_takeover (each env's
    # bot mistakes the OTHER's reply as a human admin taking over the thread).
    # Bot polling is ON in production, OFF in preview. We can't rely on env
    # vars because (a) Emergent's deployment UI doesn't expose them to the
    # user reliably and (b) we accidentally set CIRCLE_BOT_ENABLED=false in
    # production env vars while debugging in preview, with no way to remove
    # them after deployment. So we detect environment by inspecting the
    # MongoDB connection string — preview's `MONGO_URL` is the local in-
    # container Mongo at `mongodb://localhost:27017`, while production
    # uses a managed external cluster (atlas/etc). Anything that's not
    # `localhost` is treated as production.
    _mongo_url = os.environ.get("MONGO_URL") or ""
    _is_preview = "localhost" in _mongo_url or "127.0.0.1" in _mongo_url
    circle_bot_enabled = not _is_preview
    async def _circle_dm_poll():
        import circle_dm_poll
        import asyncio as _asyncio
        try:
            # Hard timeout — APScheduler's `max_instances=1` means a hung
            # poll silently drops every subsequent cron fire. Cap each
            # cycle at 90s so the watchdog actually has something to watch.
            res = await _asyncio.wait_for(circle_dm_poll.poll_once(db), timeout=90)
            if res.get("replied") or res.get("escalated") or res.get("errors"):
                logger.info(f"[scheduler] circle_dm_poll: replied={res.get('replied')} escalated={res.get('escalated')} seeded={res.get('seeded')} human_takeover={res.get('human_takeover')} errors={res.get('errors')}")
        except _asyncio.TimeoutError:
            logger.warning("[scheduler] circle_dm_poll TIMED OUT after 90s — next cron fire will pick up where this left off")
        except Exception as e:
            logger.warning(f"[scheduler] circle_dm_poll failed: {e}")

    if circle_bot_enabled:
        scheduler.add_job(
            _circle_dm_poll,
            CronTrigger(minute="*/1", timezone=tz),
            id="circle_dm_poll",
            replace_existing=True,
            max_instances=1, coalesce=True,
        )
        logger.info("[scheduler] circle_dm_poll: ENABLED (CIRCLE_BOT_DISABLED is not set)")

        # Watchdog — if a poll hangs (e.g. a Circle API call blocking for 10
        # minutes), `max_instances=1, coalesce=True` would silently drop
        # every subsequent cron fire and the bot would go dark. Every 5
        # minutes we check the persisted `last_poll_at` timestamp: if no
        # poll has completed in the last 5 minutes, we kick a fresh poll as
        # a one-shot background task. Idempotent — the next normal cron
        # fire will resume from where this leaves off.
        async def _circle_dm_poll_watchdog():
            import circle_dm_poll
            import asyncio
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td
            try:
                cfg = await circle_dm_poll.get_config(db)
                last_iso = cfg.get("last_poll_at") if cfg else None
                stale = True
                if last_iso:
                    try:
                        last = _dt.fromisoformat(last_iso.replace("Z", "+00:00"))
                        if last.tzinfo is None:
                            last = last.replace(tzinfo=_tz.utc)
                        stale = last < _dt.now(_tz.utc) - _td(minutes=5)
                    except Exception:
                        stale = True
                if stale:
                    logger.warning(f"[watchdog] circle_dm_poll appears stuck (last_poll_at={last_iso}). Kicking a one-shot poll.")
                    asyncio.create_task(_circle_dm_poll())
            except Exception as e:
                logger.warning(f"[watchdog] circle_dm_poll check failed: {e}")

        scheduler.add_job(
            _circle_dm_poll_watchdog,
            CronTrigger(minute="*/5", timezone=tz),
            id="circle_dm_poll_watchdog",
            replace_existing=True,
        )
    else:
        logger.info("[scheduler] circle_dm_poll: DISABLED (set CIRCLE_BOT_DISABLED=false to enable)")

    # Independent asyncio loop — runs OUTSIDE APScheduler so if APScheduler
    # ever dies (event-loop crash, broken job store, etc.) the bot keeps
    # polling regardless. Yesterday's outage was APScheduler silently
    # dropping cron fires for 7+ hours; the watchdog above is itself an
    # APScheduler job so it died with the rest. This task is fire-and-
    # forget — created with `asyncio.create_task` and never awaited.
    # Each iteration: sleep 60s, then run a poll with 90s hard timeout.
    # Wrapped in `while True` with broad try/except so a single failure
    # never breaks the loop.
    if circle_bot_enabled:
        import asyncio
        async def _circle_dm_poll_independent_loop():
            import asyncio
            # Initial delay so the boot sequence settles before we start.
            await asyncio.sleep(20)
            logger.info("[independent-poller] starting circle_dm_poll loop (60s cycle, 90s hard timeout per poll)")
            while True:
                try:
                    await asyncio.wait_for(_circle_dm_poll(), timeout=90)
                except asyncio.TimeoutError:
                    logger.warning("[independent-poller] poll cycle timed out (>90s)")
                except Exception as e:
                    logger.warning(f"[independent-poller] poll cycle failed: {e}")
                try:
                    await asyncio.sleep(60)
                except Exception:
                    # Sleep failure (event loop weirdness) — just spin.
                    pass
        # Hold a strong reference so Python's GC can't kill the task. Without
        # this, the Task returned by create_task has no live reference and
        # gets garbage-collected the moment on_startup exits — silently
        # killing the entire loop. The module-level list keeps it alive.
        _INDEPENDENT_POLLER_TASKS.append(
            asyncio.create_task(_circle_dm_poll_independent_loop())
        )

    # Interview-eve check-in DMs — 19:00 UK every weekday.
    # Sends a Coralie DM to every student whose interview is tomorrow,
    # asking for a 1-10 support score. Low scores → Slack alert.
    # Wrapped in run_audited so each run lands in db.scheduler_runs (the
    # Interview-eve widget reads the latest one) and failures ping Slack.
    async def _interview_eve_dms():
        import interview_eve_dm
        from scheduler_audit import run_audited
        try:
            res = await run_audited(
                db,
                "interview_eve_dms",
                lambda: interview_eve_dm.send_interview_eve_dms(db),
            )
            logger.info(f"[scheduler] interview_eve_dms: {res}")
        except Exception as e:
            logger.warning(f"[scheduler] interview_eve_dms failed: {e}")

    scheduler.add_job(
        _interview_eve_dms,
        CronTrigger(hour=19, minute=0, day_of_week="mon-fri", timezone=tz),
        id="interview_eve_dms",
        replace_existing=True,
        misfire_grace_time=3600,
        # Prevent the job running twice in parallel and collapse multiple
        # pending firings (e.g. one missed + one scheduled within the
        # misfire window) into a single run. Without this, a container
        # restart near 19:00 has been observed double-firing the job.
        max_instances=1, coalesce=True,
    )

    # Pre-warm Student Lookup cache for every private-tier student at 05:30 UK.
    # Coaches open these students 10x more often than Academy students (private
    # coaching sessions, weekly 1:1s) — warming the cache means the first open
    # of the day is instant instead of a 3-8s parallel fan-out. Academy
    # students fall back to the on-demand 30-min cache.
    async def _prewarm_private_lookups():
        import student_prewarm
        try:
            res = await student_prewarm.prewarm_private_tier_lookups(db)
            logger.info(f"[scheduler] prewarm_private_lookups: {res}")
        except Exception as e:
            logger.warning(f"[scheduler] prewarm_private_lookups failed: {e}")

    scheduler.add_job(
        _prewarm_private_lookups,
        CronTrigger(hour=5, minute=30, timezone=tz),
        id="prewarm_private_lookups",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info(
        f"[scheduler] Jobs: weekly_sync (Mon 06:00), daily_circle_refresh (05:00), "
        f"daily_cohort_refresh (05:05), daily_at_risk_refresh (05:15), daily_tally_refresh (05:20), "
        f"daily_phase_breakdown_refresh (05:25), daily_sla_digest (08:00), "
        f"spotlight_reminders (every 5 min), daily_leaderboard_snapshot (02:15) — {tz}"
    )

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

    # Initial Tally → Tickets backfill (fire-and-forget). Safe to re-run at
    # any time — uses Tally submission id as the dedup key.
    async def _initial_tickets_backfill():
        try:
            await _asyncio.sleep(45)
            import tickets as tickets_mod
            res = await tickets_mod.sync_tally(db)
            logger.info(f"[startup] tickets initial backfill: {res}")
        except Exception as e:
            logger.warning(f"[startup] tickets backfill failed: {e}")

    _asyncio.create_task(_initial_tickets_backfill())


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


@api.get("/version")
async def version():
    # Render injects RENDER_GIT_COMMIT / RENDER_GIT_REPO_SLUG at build time.
    sha = os.environ.get("RENDER_GIT_COMMIT", "")
    return {
        "commit": (sha or "unknown")[:7],
        "commit_full": sha or None,
        "repo": os.environ.get("RENDER_GIT_REPO_SLUG") or None,
        "branch": os.environ.get("RENDER_GIT_BRANCH") or None,
    }


# --- Mount routers --------------------------------------------------------
app.include_router(api)

from routes import (  # noqa: E402  -- routers depend on `api` being defined
    team as routes_team,
    rocks as routes_rocks,
    scorecard as routes_scorecard,
    sync as routes_sync,
    students as routes_students,
    interviews as routes_interviews,
    coach as routes_coach,
    cohorts as routes_cohorts,
    launches as routes_launches,
    notifications as routes_notifications,
    pulse as routes_pulse,
    spotlight as routes_spotlight,
    leaderboard as routes_leaderboard,
    tickets as routes_tickets,
    oauth_gmail as routes_oauth_gmail,
    wati as routes_wati,
    private_videos as routes_private_videos,
    today_calls as routes_today_calls,
    circle as routes_circle,
    interview_eve as routes_interview_eve,
    scheduler as routes_scheduler,
)
for _r in (
    routes_team.router, routes_rocks.router, routes_scorecard.router,
    routes_sync.router, routes_students.router, routes_interviews.router,
    routes_coach.router, routes_cohorts.router, routes_launches.router,
    routes_notifications.router, routes_pulse.router, routes_spotlight.router,
    routes_leaderboard.router, routes_tickets.router, routes_oauth_gmail.router,
    routes_wati.router, routes_private_videos.router, routes_today_calls.router,
    routes_circle.router, routes_interview_eve.router, routes_scheduler.router,
):
    app.include_router(_r)


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
