"""
OAuth + inbox management for the Gmail → Support Tickets integration.

- POST /api/oauth/gmail/start  (admin) → returns Google authorisation URL
- GET  /api/oauth/gmail/callback         → public, completes OAuth, redirects back
- GET  /api/oauth/gmail/inboxes (admin) → list connected inboxes
- DELETE /api/oauth/gmail/inboxes/{id} (admin) → disconnect an inbox
- POST /api/oauth/gmail/sync   (admin) → trigger an immediate sync of all inboxes
- GET  /api/oauth/gmail/status (admin) → integration health (configured? inbox count?)
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse

import gmail_sync
from db import db
from deps import require_admin, require_board

router = APIRouter(prefix="/api/oauth/gmail", tags=["gmail-oauth"])


@router.get("/status")
async def status(admin: dict = Depends(require_admin)):
    inboxes = await gmail_sync.list_inboxes(db)
    return {
        "configured": gmail_sync.is_configured(),
        "inbox_count": len(inboxes),
        "inboxes": inboxes,
    }


@router.post("/start")
async def start(admin: dict = Depends(require_admin), return_to: str = "/settings"):
    if not gmail_sync.is_configured():
        raise HTTPException(
            500,
            "Gmail integration not configured — admin must set GOOGLE_CLIENT_ID + "
            "GOOGLE_CLIENT_SECRET in the backend environment first.",
        )
    url = await gmail_sync.start_oauth(db, return_to=return_to)
    return {"authorize_url": url}


@router.get("/callback")
async def callback(code: str | None = None, state: str | None = None, error: str | None = None):
    """Public callback. We render a tiny HTML page that posts a message to the
    opener (settings page) and closes the popup. Falls back to a top-level
    redirect when not opened in a popup."""
    if error:
        msg = f"Google OAuth error: {error}"
        return _close_popup_html(success=False, message=msg, redirect="/settings")

    if not code or not state:
        return _close_popup_html(
            success=False,
            message="Missing OAuth code or state",
            redirect="/settings",
        )

    try:
        result = await gmail_sync.complete_oauth(db, code=code, state=state)
    except ValueError as e:
        return _close_popup_html(success=False, message=str(e), redirect="/settings")
    except Exception as e:
        return _close_popup_html(success=False, message=f"Connection failed: {e}", redirect="/settings")

    return _close_popup_html(
        success=True,
        message=f"Connected {result['email']}",
        redirect=result.get("return_to") or "/settings",
    )


@router.get("/inboxes")
async def inboxes(admin: dict = Depends(require_admin)):
    return {"inboxes": await gmail_sync.list_inboxes(db)}


@router.delete("/inboxes/{inbox_id}")
async def remove_inbox(inbox_id: str, admin: dict = Depends(require_admin)):
    ok = await gmail_sync.remove_inbox(db, inbox_id)
    if not ok:
        raise HTTPException(404, "Inbox not found")
    return {"ok": True}


@router.post("/sync")
async def sync_now(admin: dict = Depends(require_admin)):
    return await gmail_sync.sync_all(db)


# -------------------------------------------------------- Reply (send)
@router.post("/tickets/{ticket_id}/reply")
async def reply(
    ticket_id: str,
    payload: dict,
    user: dict = Depends(require_board("tickets")),
):
    """Send an email reply to an email-sourced ticket via the original inbox."""
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(400, "body required")
    from_inbox = (payload.get("from_inbox_email") or "").strip().lower() or None
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Ticket not found")
    try:
        return await gmail_sync.send_reply(db, t, body, from_inbox_email=from_inbox)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


# -------------------------------------------------------- HTML helper
def _close_popup_html(*, success: bool, message: str, redirect: str) -> HTMLResponse:
    color = "#10b981" if success else "#dc2626"
    icon = "✅" if success else "⚠️"
    safe_msg = message.replace("<", "&lt;").replace(">", "&gt;")
    safe_redirect = redirect.replace('"', "&quot;")
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Gmail OAuth</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; background:#0f172a; color:#f8fafc;
         display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }}
  .card {{ background:#1e293b; border:1px solid #334155; border-radius:12px; padding:32px; max-width:420px; text-align:center; }}
  .icon {{ font-size: 36px; margin-bottom: 8px; }}
  h1 {{ font-size: 18px; margin: 0 0 8px; color: {color}; }}
  p  {{ font-size: 14px; color:#cbd5e1; line-height:1.5; }}
  .small {{ font-size: 11px; color:#64748b; margin-top:16px; }}
</style>
</head>
<body>
  <div class="card">
    <div class="icon">{icon}</div>
    <h1>{ "Inbox connected" if success else "Connection failed" }</h1>
    <p>{safe_msg}</p>
    <p class="small">This window will close automatically.</p>
  </div>
  <script>
    try {{
      if (window.opener && !window.opener.closed) {{
        window.opener.postMessage(
          {{ type: "gmail-oauth", success: {str(success).lower()}, message: {repr(message)} }},
          window.location.origin,
        );
        setTimeout(() => window.close(), 800);
      }} else {{
        setTimeout(() => {{ window.location.replace("{safe_redirect}"); }}, 1500);
      }}
    }} catch (e) {{
      setTimeout(() => {{ window.location.replace("{safe_redirect}"); }}, 1500);
    }}
  </script>
</body></html>"""
    return HTMLResponse(content=html)
