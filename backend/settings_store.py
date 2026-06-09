"""
App-wide editable settings stored in MongoDB `app_settings` collection.
Keyed by `_id` (string). Currently used for cohort milestones.
"""
from __future__ import annotations

DEFAULT_COHORT_MILESTONES = [
    "USP Guru",
    "Verified Examples Badge",
    "Senior-Level Thinker",
    "Job Mastermind",
    "Authentic Self",
]


async def get_cohort_milestones(db) -> list[str]:
    doc = await db.app_settings.find_one({"_id": "cohort_milestones"}, {"_id": 0})
    if not doc or not doc.get("milestones"):
        return list(DEFAULT_COHORT_MILESTONES)
    ms = doc["milestones"]
    if not isinstance(ms, list) or len(ms) != 5:
        return list(DEFAULT_COHORT_MILESTONES)
    return [str(m).strip() for m in ms]


async def set_cohort_milestones(db, milestones: list[str]) -> list[str]:
    if not isinstance(milestones, list) or len(milestones) != 5:
        raise ValueError("Exactly 5 milestone names are required")
    cleaned = [str(m).strip() for m in milestones]
    if any(not m for m in cleaned):
        raise ValueError("Milestone names cannot be empty")
    await db.app_settings.update_one(
        {"_id": "cohort_milestones"},
        {"$set": {"milestones": cleaned}},
        upsert=True,
    )
    return cleaned


# ---- Coach Activity Circle space IDs (per cohort, admin-editable) -------
# End dates default to None — if unset, the SLA digest fires forever (legacy
# behaviour). Set an end date when a cohort wraps so the digest goes quiet
# until the next cohort's spaces + dates are configured.
DEFAULT_COACH_SPACES = {
    "recorded_answer_space_id": 2529508,    # /c/recorded-answer-review-apr-26/
    "interview_support_space_id": 2529509,  # /c/specific-interview-support-apr-26/
    "recorded_answer_start": "2026-05-04",
    "interview_support_start": "2026-04-23",
    "recorded_answer_end": None,
    "interview_support_end": None,
}

# Keys whose value is a date string (or None to clear). Treated specially by
# set_coach_spaces so the team can blank them out from the settings UI.
_DATE_KEYS = (
    "recorded_answer_start",
    "interview_support_start",
    "recorded_answer_end",
    "interview_support_end",
)


async def get_coach_spaces(db) -> dict:
    """Return current Coach Activity space IDs + start/end dates. Falls back
    to sensible defaults if the setting hasn't been configured yet."""
    doc = await db.app_settings.find_one({"_id": "coach_spaces"}, {"_id": 0})
    merged = dict(DEFAULT_COACH_SPACES)
    if doc:
        merged.update({k: v for k, v in doc.items() if v is not None})
    try:
        merged["recorded_answer_space_id"] = int(merged["recorded_answer_space_id"])
        merged["interview_support_space_id"] = int(merged["interview_support_space_id"])
    except (TypeError, ValueError):
        merged["recorded_answer_space_id"] = DEFAULT_COACH_SPACES["recorded_answer_space_id"]
        merged["interview_support_space_id"] = DEFAULT_COACH_SPACES["interview_support_space_id"]
    return merged


async def set_coach_spaces(db, payload: dict) -> dict:
    allowed = set(DEFAULT_COACH_SPACES.keys())
    update: dict = {}
    for k, v in payload.items():
        if k not in allowed:
            continue
        # Date fields: empty string / None means "clear the override" (revert
        # to default, i.e. None for end dates so the digest fires again).
        if k in _DATE_KEYS:
            if v in (None, "", "null"):
                update[k] = None
            else:
                update[k] = v
            continue
        if v is None:
            continue
        update[k] = v
    if not update:
        raise ValueError("No valid fields supplied")
    for k in ("recorded_answer_space_id", "interview_support_space_id"):
        if k in update:
            try:
                update[k] = int(update[k])
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be an integer")
    await db.app_settings.update_one(
        {"_id": "coach_spaces"},
        {"$set": update},
        upsert=True,
    )
    return await get_coach_spaces(db)


async def get_active_quarter(db, fallback_quarters: list[str] | None = None) -> str | None:
    """Returns the current active quarter ID (e.g. 'Q2 2026'), or the most
    recent quarter from `fallback_quarters` if no setting exists yet."""
    doc = await db.app_settings.find_one({"_id": "active_quarter"}, {"_id": 0})
    if doc and doc.get("quarter"):
        return doc["quarter"]
    if fallback_quarters:
        return fallback_quarters[0]  # caller passes already-sorted-desc list
    quarters = await db.rocks.distinct("quarter")
    if quarters:
        return sorted(quarters, reverse=True)[0]
    return None


async def set_active_quarter(db, quarter: str) -> str:
    quarter = quarter.strip()
    await db.app_settings.update_one(
        {"_id": "active_quarter"},
        {"$set": {"quarter": quarter}},
        upsert=True,
    )
    return quarter



# ---- Gmail inbox → assignee auto-routing ---------------------------------
DEFAULT_INBOX_ROUTING: list[dict] = [
    # Each rule maps inbox local-parts (before @) to a team member name.
    {"inbox_locals": ["tessa", "arub"], "team_member_name": "Arub Yousuf"},
    {"inbox_locals": ["oksana", "coralie"], "team_member_name": "Coralie Fairon"},
]


async def get_inbox_routing(db) -> list[dict]:
    """Return the current rule list. Each rule:
        {inbox_locals: [str, …], team_member_name: str}
    """
    doc = await db.app_settings.find_one({"_id": "inbox_routing"}, {"_id": 0})
    if not doc or not isinstance(doc.get("rules"), list):
        return [dict(r) for r in DEFAULT_INBOX_ROUTING]
    out: list[dict] = []
    for r in doc["rules"]:
        locals_ = [str(x).strip().lower() for x in (r.get("inbox_locals") or []) if str(x).strip()]
        name = (r.get("team_member_name") or "").strip()
        if locals_ and name:
            out.append({"inbox_locals": locals_, "team_member_name": name})
    return out


async def set_inbox_routing(db, rules: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for r in rules or []:
        if not isinstance(r, dict):
            continue
        raw_locals = r.get("inbox_locals") or []
        if isinstance(raw_locals, str):
            raw_locals = [x for x in raw_locals.replace(",", " ").split() if x]
        locals_ = [str(x).strip().lower().lstrip("@").split("@", 1)[0] for x in raw_locals]
        locals_ = [x for x in locals_ if x]
        name = (r.get("team_member_name") or "").strip()
        if locals_ and name:
            cleaned.append({"inbox_locals": locals_, "team_member_name": name})
    await db.app_settings.update_one(
        {"_id": "inbox_routing"},
        {"$set": {"rules": cleaned}},
        upsert=True,
    )
    return cleaned


# ---- Private-chat coach config (Route 2, see PRIVATE_CHAT_MIGRATION.md) ----
# The coaches added to every new private-tier group chat. Ported from the
# Zapier "coach list" table — same people for every student, occasionally
# edited. One coach is the `sender`: their Circle token creates the room and
# posts the welcome message. Emails are each coach's CIRCLE login email
# (resolved to a community_member_id at create time); seeded blank for the
# admin to fill in the Settings card. Oksana intentionally excluded (offboarded).
DEFAULT_PRIVATE_CHAT_COACHES: list[dict] = [
    {"name": "Tessa", "email": ""},
    {"name": "Arub", "email": ""},
    {"name": "Coralie", "email": ""},
    {"name": "Becky", "email": ""},
]

# Opening message posted into each new chat (by the sender coach). `{first_name}`
# is substituted. Placeholder default — replace with the exact wording the
# current zaps use before going live.
DEFAULT_PRIVATE_CHAT_WELCOME = (
    "Hi {first_name}! 👋 Welcome to your private coaching chat. This is where "
    "you'll get your personalised video feedback and can ask us anything. "
    "We're excited to work with you!"
)


def _clean_coach_list(raw) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for c in raw or []:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        email = (c.get("email") or "").strip().lower()
        if not name:
            continue
        key = email or name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "email": email})
    return out


async def get_private_chat_config(db) -> dict:
    """Return {coaches: [{name, email}], sender_email}. Defaults to the seeded
    coach list (emails blank) until configured."""
    doc = await db.app_settings.find_one({"_id": "private_chat"}, {"_id": 0})
    coaches = _clean_coach_list((doc or {}).get("coaches")) or [
        dict(c) for c in DEFAULT_PRIVATE_CHAT_COACHES
    ]
    sender_email = ((doc or {}).get("sender_email") or "").strip().lower()
    # Sender must be one of the configured coaches (with an email); else blank.
    coach_emails = {c["email"] for c in coaches if c["email"]}
    if sender_email not in coach_emails:
        sender_email = ""
    welcome = (doc or {}).get("welcome_template")
    if not (welcome or "").strip():
        welcome = DEFAULT_PRIVATE_CHAT_WELCOME
    return {"coaches": coaches, "sender_email": sender_email, "welcome_template": welcome}


async def set_private_chat_config(db, payload: dict) -> dict:
    """Replace the coach list and/or sender. `sender_email` must match one of
    the supplied coaches' emails."""
    coaches = _clean_coach_list((payload or {}).get("coaches"))
    if not coaches:
        raise ValueError("At least one coach is required")
    sender_email = ((payload or {}).get("sender_email") or "").strip().lower()
    coach_emails = {c["email"] for c in coaches if c["email"]}
    if sender_email and sender_email not in coach_emails:
        raise ValueError("sender_email must be one of the coaches' emails")
    update = {"coaches": coaches, "sender_email": sender_email}
    if "welcome_template" in (payload or {}):
        update["welcome_template"] = (payload.get("welcome_template") or "").strip()
    await db.app_settings.update_one(
        {"_id": "private_chat"},
        {"$set": update},
        upsert=True,
    )
    return await get_private_chat_config(db)
