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


# ---- Per-cohort Cohort-Dashboard config (admin-editable) ----------------
# Each cohort's ConvertKit "Cohort - New" / "Cohort - Legacy" tag IDs, its
# Circle cross-reference tag, and its Circle "Introduce Yourself" space id.
# Lets the Cohort Dashboard work for any cohort without a code change each
# launch. Keyed by the exact Monday "Cohort Joined" label (e.g. "June 26").
# NB Circle tags use the FULL month for some cohorts ("June '26") but an
# abbreviation for others ("Apr '26") - so it's stored explicitly, never
# derived.
# String fields stored verbatim; integer fields coerced to int.
_COHORT_CFG_STR_KEYS = (
    "circle_tag", "early_access_cutoff", "prev_cohort_name", "prev_cohort_curriculum_url",
)
_COHORT_CFG_INT_KEYS = (
    "new_tag_id", "legacy_tag_id", "intros_space_id",
    "prev_cohort_space_id", "bonus_calls_space_id", "in_between_tag_id",
)

DEFAULT_COHORT_CONFIGS: dict = {
    "April 26": {
        "circle_tag": "Apr '26",
        "new_tag_id": 14407610,
        "legacy_tag_id": 14407628,
        "intros_space_id": 2529515,
    },
    "June 26": {
        "circle_tag": "June '26",
        "new_tag_id": 19550942,
        "legacy_tag_id": 19550968,
        "intros_space_id": 2647286,
        # Early-interview access (course catch-up): students whose interview is
        # on/before the cutoff get added to the PREVIOUS cohort's curriculum
        # space and/or the Bonus Live Sessions space (Sunday group coaching).
        "early_access_cutoff": "2026-07-19",         # end of Week 3, June 26 cohort
        "prev_cohort_name": "April 26",
        "prev_cohort_space_id": 2529501,             # AYCI Curriculum - April 26
        "prev_cohort_curriculum_url": "https://ayci-academy.circle.so/c/ayci-curriculum-apr-26/",
        "bonus_calls_space_id": 1944718,             # Bonus Live Sessions (permanent)
        # Early-interview inclusion = anyone in EITHER of these Kit tags (new
        # June signups, or "in between" gap-joiners) with a soon interview.
        # new_tag_id (above) doubles as the "Cohort - New" tag.
        "in_between_tag_id": 19785979,               # [AYCI JUN-26] In Between
    },
}


async def get_cohort_configs(db) -> dict:
    """Return {cohort_label: {circle_tag, new/legacy/intros ids, and the
    early-access fields}}. The stored doc is merged OVER the seeded defaults so
    editing one cohort never silently drops the known ones."""
    doc = await db.app_settings.find_one({"_id": "cohort_configs"}, {"_id": 0})
    merged = {k: dict(v) for k, v in DEFAULT_COHORT_CONFIGS.items()}
    stored = (doc or {}).get("configs") or {}
    if isinstance(stored, dict):
        for label, cfg in stored.items():
            if isinstance(cfg, dict):
                merged[str(label)] = {**merged.get(str(label), {}), **cfg}
    return merged


async def set_cohort_configs(db, configs: dict) -> dict:
    """Upsert the per-cohort config map. Each incoming cohort entry is MERGED
    over what's already stored for that cohort, so a caller that only sends a
    subset of fields (e.g. the Cohort Dashboard card) never wipes the
    early-access fields, and vice-versa. Validates field types."""
    if not isinstance(configs, dict) or not configs:
        raise ValueError("configs must be a non-empty object keyed by cohort label")
    doc = await db.app_settings.find_one({"_id": "cohort_configs"}, {"_id": 0})
    stored = {k: dict(v) for k, v in ((doc or {}).get("configs") or {}).items() if isinstance(v, dict)}
    for label, cfg in configs.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"config for '{label}' must be an object")
        entry: dict = {}
        for k in _COHORT_CFG_STR_KEYS:
            if k in cfg:
                s = str(cfg.get(k) or "").strip()
                if s:
                    entry[k] = s
        for k in _COHORT_CFG_INT_KEYS:
            if k not in cfg:
                continue
            v = cfg.get(k)
            if v in (None, ""):
                continue
            try:
                entry[k] = int(v)
            except (TypeError, ValueError):
                raise ValueError(f"{k} for '{label}' must be a whole number")
        key = str(label).strip()
        stored[key] = {**stored.get(key, {}), **entry}
    await db.app_settings.update_one(
        {"_id": "cohort_configs"},
        {"$set": {"configs": stored}},
        upsert=True,
    )
    return stored


# ---- Coach Activity Circle space IDs (per cohort, admin-editable) -------
# End dates default to None - if unset, the SLA digest fires forever (legacy
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
# Zapier "coach list" table - same people for every student, occasionally
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

# Opening message posted into each new chat (by the sender coach), keyed by
# audience (tier / B&G level) because the tier name, video allowance and links
# differ. Placeholders substituted at send time: {first_name} {last_name}
# {full_name} {email} {tier} {video_allowance}. Author pastes full URLs with
# placeholders inline (e.g. a Tally link with ?name={first_name}&…).
#
# Audience keys: private_plus | vip | boost_and_go | boost_and_go_plus
# (+ "legacy" etc. can be added later). A student with no template for their
# audience is BLOCKED from auto-create (we won't send the wrong tier's message).
#
# Seeded from the live Private Plus message (Tessa, 2026-06-09 screenshot).
DEFAULT_PRIVATE_CHAT_WELCOME_TEMPLATES: dict = {
    "private_plus": (
        "Hi {first_name},\n\n"
        "This is your private chat as a {tier} member, where you can ask any "
        "questions and receive answers from the faculty.\n\n"
        "You can book your 1:1 call here: https://calendly.com/d/cxkz-kf9-xb4/ayci-1-1-30-min\n\n"
        "You can also submit up to {video_allowance} video answers for feedback "
        "from the coaches. Please upload them here:\n"
        "https://tally.so/r/0Qr5py?name={first_name}&lastname={last_name}&email={email}\n\n"
        "As a {tier} member, you can access your personalised interview prep "
        "timeline here:\n"
        "https://ayci-academy.circle.so/c/your-personal-interview-prep-timeline\n\n"
        "You can log in using your Circle details"
    ),
}


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
    templates = (doc or {}).get("welcome_templates")
    if not isinstance(templates, dict) or not templates:
        templates = dict(DEFAULT_PRIVATE_CHAT_WELCOME_TEMPLATES)
    else:
        templates = {str(k): (v or "") for k, v in templates.items()}
    return {"coaches": coaches, "sender_email": sender_email, "welcome_templates": templates}


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
    if "welcome_templates" in (payload or {}):
        raw = payload.get("welcome_templates") or {}
        if not isinstance(raw, dict):
            raise ValueError("welcome_templates must be an object keyed by audience")
        # Keep only non-empty templates; normalise keys.
        update["welcome_templates"] = {
            str(k).strip(): (v or "").strip()
            for k, v in raw.items()
            if str(k).strip() and (v or "").strip()
        }
    await db.app_settings.update_one(
        {"_id": "private_chat"},
        {"$set": update},
        upsert=True,
    )
    return await get_private_chat_config(db)
