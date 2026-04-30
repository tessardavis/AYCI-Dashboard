"""SLA + Slack notifications for unanswered Circle posts."""
from fastapi import APIRouter, Depends

import sla_notifications
from db import db
from deps import get_current_user, require_admin

router = APIRouter(prefix="/api", tags=["notifications"])


@router.get("/notifications/sla/count")
async def sla_unanswered_count(user: dict = Depends(get_current_user)):
    """Live count of >48h unanswered Circle posts (for the nav bell badge).
    Cheap: pulls from the cached coach-activity summary."""
    count = await sla_notifications.count_unanswered(db)
    return {"unanswered_count": count}


@router.post("/notifications/slack/test")
async def slack_test_send(admin: dict = Depends(require_admin)):
    """Admin-only: send the SLA digest to Slack right now (manual trigger)."""
    return await sla_notifications.send_sla_digest(db)
