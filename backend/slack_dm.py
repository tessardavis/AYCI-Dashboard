"""
Slack bot DM helpers - sends a private message to any team member by email.

We use Slack's Web API (`chat.postMessage` + `users.lookupByEmail`) rather
than incoming webhooks because incoming webhooks can't deliver true 1:1 DMs
to arbitrary users.

Required Slack app scopes (Bot Token):
  - chat:write          (post messages)
  - users:read          (find users)
  - users:read.email    (find by email)
  - im:write            (open DM channels - auto-granted via chat:write)

Token storage: same DB-backed pattern as the circle-days webhook. Reads
`app_settings.slack_bot_token.value`, falls back to env `SLACK_BOT_TOKEN`.
This means the user can configure on production without an env-var redeploy.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"


# -------------------------------------------------------- Token storage
async def get_bot_token(db) -> str:
    doc = await db.app_settings.find_one(
        {"id": "slack_bot_token"}, {"_id": 0, "value": 1}
    )
    db_val = (doc or {}).get("value") or ""
    return (db_val.strip() or os.environ.get("SLACK_BOT_TOKEN") or "").strip()


async def set_bot_token(db, value: str) -> dict:
    value = (value or "").strip()
    if value and not value.startswith("xoxb-"):
        return {"ok": False, "error": "Slack bot tokens start with 'xoxb-'"}
    await db.app_settings.update_one(
        {"id": "slack_bot_token"},
        {"$set": {"id": "slack_bot_token", "value": value}},
        upsert=True,
    )
    return {"ok": True, "configured": bool(value)}


# -------------------------------------------------------- Email override
async def _resolve_slack_email(db, email: str) -> str:
    """If the team member registered an explicit `slack_email` (because
    their Slack account uses a different address than the one they log
    into the dashboard with), use that for the Slack lookup. Otherwise
    pass the original through.

    Resolution: users.email → users.team_member_id → team_members.slack_email
    """
    if not email:
        return email
    email_l = email.strip().lower()
    user = await db.users.find_one(
        {"email": email_l}, {"_id": 0, "team_member_id": 1}
    )
    tm_id = (user or {}).get("team_member_id")
    if not tm_id:
        return email_l
    member = await db.team_members.find_one(
        {"id": tm_id}, {"_id": 0, "slack_email": 1}
    )
    override = ((member or {}).get("slack_email") or "").strip().lower()
    return override or email_l


# -------------------------------------------------------- Email-cached lookup
async def _user_id_for_email(db, token: str, email: str) -> Optional[str]:
    """Look up a Slack user_id by email. Cache the result indefinitely in
    `slack_user_cache` since emails-to-IDs almost never change."""
    email_l = email.strip().lower()
    if not email_l:
        return None
    cached = await db.slack_user_cache.find_one(
        {"_id": email_l}, {"_id": 0, "user_id": 1}
    )
    if cached and cached.get("user_id"):
        return cached["user_id"]
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{SLACK_API}/users.lookupByEmail",
                headers={"Authorization": f"Bearer {token}"},
                params={"email": email_l},
            )
        data = r.json()
    except Exception as e:
        logger.warning(f"[slack-dm] lookupByEmail failed for {email_l}: {e}")
        return None
    if not data.get("ok"):
        logger.info(f"[slack-dm] no Slack user for {email_l}: {data.get('error')}")
        return None
    user_id = (data.get("user") or {}).get("id")
    if user_id:
        await db.slack_user_cache.update_one(
            {"_id": email_l},
            {"$set": {"_id": email_l, "user_id": user_id}},
            upsert=True,
        )
    return user_id


# -------------------------------------------------------- DM
async def dm_user(db, email: str, text: str, *, blocks: Optional[list] = None) -> dict:
    """Send a private DM to a user identified by their email. Returns
    {ok, error, ts} from Slack."""
    token = await get_bot_token(db)
    if not token:
        return {"ok": False, "error": "no bot token configured"}
    if not email:
        return {"ok": False, "error": "no email provided"}
    email = await _resolve_slack_email(db, email)
    user_id = await _user_id_for_email(db, token, email)
    if not user_id:
        return {"ok": False, "error": f"no Slack account for {email}"}
    payload = {"channel": user_id, "text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{SLACK_API}/chat.postMessage",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
        data = r.json()
    except Exception as e:
        logger.warning(f"[slack-dm] postMessage failed: {e}")
        return {"ok": False, "error": str(e)}
    if not data.get("ok"):
        logger.warning(f"[slack-dm] Slack rejected DM to {email}: {data.get('error')}")
    return data


# -------------------------------------------------------- Channel post
async def post_to_channel(db, channel: str, text: str, *, blocks: Optional[list] = None) -> dict:
    """Post a message to a Slack channel (e.g. "#fulfillment-team" or a channel
    ID) via the same bot token. The bot must be a member of the channel
    (/invite @<bot> once). Returns {ok, error, ts}."""
    token = await get_bot_token(db)
    if not token:
        return {"ok": False, "error": "no bot token configured"}
    if not channel:
        return {"ok": False, "error": "no channel provided"}
    payload = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{SLACK_API}/chat.postMessage",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
        data = r.json()
    except Exception as e:
        logger.warning(f"[slack-dm] channel postMessage failed: {e}")
        return {"ok": False, "error": str(e)}
    if not data.get("ok"):
        logger.warning(f"[slack-dm] Slack rejected post to {channel}: {data.get('error')}")
    return data
