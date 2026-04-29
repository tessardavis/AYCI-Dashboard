"""
Pydantic data models for the AYCI Team Dashboard.

Pure data classes — no DB calls, no FastAPI dependencies. Imported by both
the main server module and any route modules under /app/backend/routes.
"""
from __future__ import annotations

import uuid
from typing import List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


# ---------- Auth -------------------------------------------------------------
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
    password: Optional[str] = None
    team_member_id: Optional[str] = None


class ChangePasswordInput(BaseModel):
    current_password: str
    new_password: str


# ---------- Team -------------------------------------------------------------
class TeamMember(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    role_title: str
    avatar_url: Optional[str] = None


class TeamMemberCreate(BaseModel):
    name: str
    role_title: str
    avatar_url: Optional[str] = None


# ---------- Metrics ----------------------------------------------------------
MetricFormat = Literal["number", "currency", "percentage"]
MetricCategory = Literal[
    "GROWTH + INTEREST",
    "CONVERSION + INTENT",
    "REVENUE",
    "SOCIAL PROOF",
    "DELIVERY + OPERATIONS",
]


class Metric(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    category: MetricCategory
    owner_ids: List[str] = []
    goal: Optional[float] = 0
    format: MetricFormat = "number"
    order: int = 0
    goal_direction: Literal["above", "below"] = "above"
    source_type: Optional[str] = None
    source_params: Optional[dict] = None
    cohort_only: bool = False
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


# ---------- Weekly values ----------------------------------------------------
class WeeklyValue(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    metric_id: str
    week_start: str
    value: float


class WeeklyValueInput(BaseModel):
    metric_id: str
    week_start: str
    value: float


# ---------- Rocks ------------------------------------------------------------
RockStatus = Literal["on_track", "off_track", "done"]


class Rock(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    owner_id: str
    title: str
    status: RockStatus = "on_track"
    due_date: str
    notes: str = ""
    quarter: str


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


# ---------- Launches ---------------------------------------------------------
class LaunchPhase(BaseModel):
    start: Optional[str] = None
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
    early_signups: Optional[LaunchPhase] = None
    legacy_upgrades: Optional[LaunchPhase] = None
    in_between: Optional[LaunchPhase] = None


class Launch(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    code: Optional[str] = None
    start_date: str
    end_date: Optional[str] = None
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
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    launch_id: str
    total_registrations: float = 0
    webinar_attendance_rate: float = 0
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
    date: str
    count: float


class DailyRegistrationInput(BaseModel):
    launch_id: str
    date: str
    count: float
