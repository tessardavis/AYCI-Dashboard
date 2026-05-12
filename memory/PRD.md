# AYCI Academy Team Dashboard — PRD

## Original Problem Statement
Robust customer service support ticket system integrating Tally forms, Gmail, Wati (WhatsApp), Monday.com, Calendly, and Circle.so. Replaces Monday.com Private Tier Video Submissions with a native UI. Adds Slack notifications, Drive document summaries, Calendly booking allowance alerts, AI-generated call briefings, and an AI auto-responder for Circle community DMs.

## Tech Stack
- React 18 + Vite + Tailwind + shadcn/ui
- FastAPI + Motor (async MongoDB)
- APScheduler for cron jobs (Europe/London tz)
- Claude Sonnet 4.5 via Emergent LLM Key for AI features
- Integrations: Stripe, ConvertKit, Gmail OAuth, Wati, Calendly, Monday.com, Slack, Circle.so (Admin + Headless APIs), Zapier

## Implemented Features (latest first)

### 2026-05-12 — Circle DM Bot v2 (polling-based)
- **What changed:** Replaced Circle Workflow webhook approach with continuous polling. Circle workflows only fire once per member, which made testing impossible and meant the bot could never respond to follow-ups from the same student. Polling solves both.
- **Loop:** every 1 minute, for each enabled coach admin (currently just Tessa), fetch their `chat_threads` via Headless API, filter to `kind=direct` (1:1 DMs only), then per-thread:
  - First-sight → seed latest message id, don't reply to backlog
  - Coach reply detected (admin message NOT in our `sent_message_ids`) → mark `human_takeover`, back off permanently
  - Student says "create a ticket" / "talk to human" / similar → escalation reply + ticket
  - Sensitive keyword (refund / urgent / complaint) → escalation reply + ticket + Slack Coralie
  - Playbook covers it → AI reply with disclosure, stay active
  - Playbook doesn't cover it → escalation reply + ticket
- **Reply format:** Always prefixed with `"Hi {first}, this is an auto-response from {coach}'s account."` per user request.
- **Hard cap:** 8 AI replies per thread per day to prevent runaway loops.
- **Settings UI (Settings → Bot):** live polling status, watched-threads table with state pills (active/escalated/human_takeover), per-thread Re-arm button, pause/resume toggle, manual "Poll now" button. Coach playbook editor moved into same tab. Legacy webhook events kept as a collapsible debug list.
- **Files:** `backend/circle_dm_poll.py` (NEW), `backend/circle_api.py` (added `list_dm_threads`, `list_thread_messages_for_admin`, `post_dm_message`, `get_cached_admin_member_id`), `backend/routes/circle.py` (added `/bot/status`, `/bot/config`, `/bot/poll-now`, `/bot/reset-thread/{uuid}`), `backend/server.py` (added `_circle_dm_poll` scheduler job, every 1 min), `frontend/src/pages/Settings.jsx` (replaced static playbook section with dynamic bot dashboard).
- **New collection:** `circle_dm_threads` `{id, thread_uuid, coach_admin_email, student_member_id, student_name, state, last_seen_message_id, sent_message_ids, ai_reply_count_today, ai_reply_count_date, escalated_ticket_id, escalation_reason, last_reply_text, last_reply_at, first_seen_at, last_activity_at}`
- **New config doc:** `app_settings { id:"circle_dm_bot_config", enabled, coach_emails, last_poll_at, last_poll_summary }`

### Earlier in this fork
- Timeline Tooltip for Past Coaches UI (`pages/UpcomingInterviews.jsx`)
- Scorecard waitlist fixes (ConvertKit burst-filtering + dynamic tag resolution)
- Wati 24h window expiration bug fix
- Over-allowance Calendly booking alerts + Acknowledge feature
- Private Video Submissions data-source transparency (Tally vs Monday)
- Circle DM Bot v1 foundation (Headless API token exchange, webhook endpoint, Settings Bot tab)

## Pending Tasks

### P1 — Upcoming
- Slack daily support-tickets digest @ 8am UK (top 3 overdue + counts by priority)
- Personalised Slack DM kickstart @ 9am UK weekdays ("You have N open / M overdue")

### P2 — Future
- Enriched Linked Student card in ticket UI (interview date, at-risk, Pulse signal)
- Pulse Score history + per-pillar drill-through
- Settings UI for TEAM_ACCOUNT_EMAILS / Spotlight cutoff / routing rules
- WhatsApp template-message starter kit
- Refactor `SupportTickets.jsx` (>2000 lines) and `PrivateVideos.jsx` (>800 lines)
- Multi-coach expansion of Circle DM Bot (Coralie + others) — config UI already supports this

## Key Endpoints
- `GET /api/circle/bot/status` — polling state + watched threads
- `PUT /api/circle/bot/config` — toggle enabled / update coach_emails
- `POST /api/circle/bot/poll-now` — force single poll cycle
- `POST /api/circle/bot/reset-thread/{uuid}` — re-arm an escalated/human_takeover thread
- `POST /api/circle/dm-webhook` — kept as legacy webhook receiver
- `GET/PUT /api/circle/coach-playbook` — bot's knowledge base

## Credentials (test)
- `admin@ayci.com` / `Admin@2026`
