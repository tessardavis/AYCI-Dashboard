# AYCI Dashboard — Onboarding

A web app that replaced the Monday.com "Academy Members" board as the team's source of truth for students of Ace Your Consultant Interview (AYCI). It mirrors the Monday board (~15-min sync) while progressively *owning* fields (interview dates, private-chat status, Boost & Go) so it can outlive Monday. Open this guide in Claude Code to ask questions about either the **team workflows** or the **code**.

## Start here
- **`TEAM_SOP.md`** — the non-technical team SOP: private chats, video allowances, interview-date reschedules, support tickets, Boost & Go. Read this for "how does the team actually use it / how is it supposed to behave."
- **`DASHBOARD_STATUS.md`** — running migration status, recent changes per session, and to-dos. The portable record of where things stand.
- **`ZAPIER_AUDIT.md`** — per-zap detail for the Monday-retirement migration.
- **`PRIVATE_CHAT_SOP.md`** / **`PRIVATE_CHAT_MIGRATION.md`** — deeper private-chat detail.

## Stack & layout
- **`backend/`** — FastAPI (`/api` router), MongoDB via Motor, APScheduler cron jobs. Hosted on **Render** (persistent disk for the private-video cache; secret files under `/etc/secrets/`).
- **`frontend/`** — React + Vite, served via **Vercel** (proxies `/api` to the backend, ~30s timeout). Cookie-based auth; role/board-gated pages.
- Integrations: **Circle** (community + DMs), **Stripe** (charges/refunds), **WATI** (WhatsApp), **Tally** (forms, incl. the interview-date form), **Kajabi** (purchases), **Google Calendar** (interview events), **Zapier** (glue being migrated into the dashboard).

## Key concepts to know
- **Mirror + pinning** — the dashboard mirrors Monday but pins dashboard-owned fields (`dashboard_edited_fields`, `PROTECTED_FIELDS`) so a sync can't clobber them.
- **Dual-email problem** — students may use different emails on Kajabi vs Circle; matching keys on both where possible.
- **Circle ids gotcha** — a chat message's sender id is a `community_member_id`; `other_participants_preview[].id` is a *different* id space. Never compare across them (see `backend/circle_dm_triage.py`).
- **Send-free Circle DM triage** — DMs become support tickets but the app never auto-replies (`CIRCLE_TRIAGE_ENABLED`; the old auto-responder bot is hard-disabled).
- **Tally-authoritative interview dates** — most-recently-submitted Tally date wins; the Google Calendar is auto-healed to match (`backend/interview_date_reconcile.py`, `backend/google_calendar.py`).

## Useful admin endpoints (browser GET, admin-authed)
- `/api/admin/circle-triage/run` — run the DM→ticket triage and see per-coach diagnostics.
- `/api/admin/interview-date/reconcile` — pull latest Tally dates now.
- `/api/admin/boost-and-go/audit` and `/api/admin/boost-and-go/backfill` — reconcile B&G flags against Stripe.
- `/api/wati/health` — WhatsApp pipeline health (the "WhatsApp · errors" badge).
