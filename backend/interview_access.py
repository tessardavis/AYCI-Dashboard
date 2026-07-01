"""
Interview-date -> Circle access grants (Deep Dive 5 + specialty spaces).

When a student tells us their interview date (Tally interview form -> the dashboard
webhook), they should get:
  - the **Deep Dive 5** space, and
  - their **specialty** space(s), per the mapping below.

This replaces the fragile Monday-triggered zaps 7 ("Deep Dive access") + 7b
("Speciality Space access"). The dashboard already matched the student robustly
(multi-email), so no dual-email misses; adds go through the idempotent
circle_api.add_member_to_space (Admin v1, the same path the old Zapier step used);
and an UNMAPPED specialty is flagged to Slack instead of silently granting nothing
(the failure mode that missed Kate Bowman).

Mapping source: the "Specialty spaces" Google Sheet. If that sheet changes, update
SPECIALTY_SPACES here.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEEP_DIVE_SPACE_ID = 1194525  # "Deep Dive 5: Common Unexpected Questions From This Year"

_MEDICINE = 2076888   # Medical Specialties
_SURGERY = 2076884    # Surgical Specialties
_PAEDS = 2076817      # Paediatrics + Subspecialties
_ITU = 2076741        # Anaesthetics and ITU
_EM = 2076744         # EM
_PEM = 2076811        # PEM
_ORTHO = 2076902      # Ortho / T+O
_RADIOLOGY = 2076906  # Radiology

# specialty (normalised) -> list of Circle space ids to add them to.
SPECIALTY_SPACES: dict[str, list[int]] = {
    "anaesthetics": [_ITU],
    "intensive care medicine": [_ITU],
    "cardiology": [_MEDICINE],
    "endocrinology": [_MEDICINE],
    "gastroenterology": [_MEDICINE],
    "general medicine": [_MEDICINE],
    "geriatrics": [_MEDICINE],
    "haematology": [_MEDICINE],
    "histopatholoy": [_MEDICINE],   # sheet spelling
    "histopathology": [_MEDICINE],  # correct spelling alias
    "infectious diseases": [_MEDICINE],
    "medical oncology": [_MEDICINE],
    "nephrology": [_MEDICINE],
    "neurology": [_MEDICINE],
    "oncology": [_MEDICINE],
    "pain medicine": [_MEDICINE],
    "psychiatry": [_MEDICINE],
    "rehab medicine": [_MEDICINE],
    "respiratory": [_MEDICINE],
    "rheumatology": [_MEDICINE],
    "em": [_EM, _PEM],
    "neonatology": [_PAEDS],
    "paediatrics - emergency medicine": [_PAEDS, _PEM, _EM],
    "paediatrics - general": [_PAEDS],
    "paediatrics - neonatology": [_PAEDS],
    "paediatrics - neurology": [_PAEDS],
    "paediatrics - respiratory": [_PAEDS],
    "paediatrics - subspecialty": [_PAEDS],
    "radiology": [_RADIOLOGY],
    "surgery - colorectal": [_SURGERY],
    "surgery - ent": [_SURGERY],
    "surgery - general": [_SURGERY],
    "surgery - gynaecology": [_SURGERY],
    "surgery - o+g": [_SURGERY],
    "surgery - oncoplastic breast": [_SURGERY],
    "surgery - ophthalmology": [_SURGERY],
    "surgery - urology": [_SURGERY],
    "surgery - vascular": [_SURGERY],
    "surgery - orthopaediatrics": [_ORTHO],
    "surgery - t+o": [_ORTHO],
}

SLACK_CHANNEL = "#fulfillment-team"


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s*-\s*", " - ", s)   # standardise spacing around hyphens
    return re.sub(r"\s+", " ", s).strip()


def match_specialty(specialty: str) -> tuple[str | None, list[int]]:
    """Return (matched_key, space_ids). ('', []) if no confident match."""
    key = _norm(specialty)
    if key and key in SPECIALTY_SPACES:
        return key, list(SPECIALTY_SPACES[key])
    return None, []


async def grant_interview_access(db, row: dict, specialty: str) -> dict:
    """Grant Deep Dive 5 + the specialty space(s) for a student who's told us their
    interview date. Idempotent + deduped via `interview_access_spaces`. Flags an
    unmapped specialty to Slack (still grants Deep Dive). Returns a report."""
    import circle_api

    email = (row.get("circle_email") or row.get("email") or "").strip().lower()
    name = row.get("name") or email
    if not email:
        return {"ok": False, "reason": "no email"}

    matched_key, spec_spaces = match_specialty(specialty)
    targets = [DEEP_DIVE_SPACE_ID] + spec_spaces
    already = set(row.get("interview_access_spaces") or [])
    to_add = [s for s in targets if s not in already]

    added, failed = [], []
    for sid in to_add:
        res = await circle_api.add_member_to_space(db, sid, email)
        (added if res.get("ok") else failed).append(sid)

    now = datetime.now(timezone.utc)
    if added:
        new_set = sorted(already | set(added))
        pinned = sorted(set(row.get("dashboard_edited_fields") or [])
                        | {"interview_access_spaces", "interview_access_granted_at"})
        await db.academy_members.update_one({"_id": row["_id"]}, {"$set": {
            "interview_access_spaces": new_set,
            "interview_access_granted_at": now,
            "dashboard_edited_fields": pinned,
            "dashboard_edited_at": now,
            "dashboard_edited_by": "interview-access",
        }})

    # Unmapped specialty -> flag so a human adds the specialty space by hand (never
    # silent, which is what let Kate slip through the old Monday zap).
    unmapped = bool(specialty) and matched_key is None
    if unmapped or failed:
        try:
            import slack_dm
            bits = [f"*Interview access* for *{name}* ({email})."]
            if unmapped:
                bits.append(f"Specialty *\"{specialty}\"* isn't in the mapping - "
                            "add their specialty space by hand (Deep Dive 5 was still granted).")
            if failed:
                bits.append(f"Failed to add spaces {failed} - check Circle.")
            await slack_dm.post_to_channel(db, SLACK_CHANNEL, " ".join(bits))
        except Exception as e:
            logger.warning(f"[interview-access] slack alert failed: {e}")

    report = {"ok": True, "email": email, "specialty": specialty,
              "matched_specialty": matched_key, "added": added, "failed": failed,
              "already_had": sorted(already), "unmapped": unmapped}
    logger.info(f"[interview-access] {name}: {report}")
    return report
