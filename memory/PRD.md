# AYCI Customer Service Dashboard - PRD

## Original Problem Statement
A robust customer-service / coaching-operations dashboard for AYCI Academy that integrates Tally forms, Gmail, Wati (WhatsApp), Monday.com, Calendly, Circle.so, and Slack - replacing several point-tools with one operational cockpit.

## Core Product Pillars
1. **Support Ticket Kanban / Table board** with 2-way Gmail and WhatsApp sync.
2. **Circle.so DM AI bot** - polls Circle community DMs, replies to FAQ-bucketed messages from a playbook, escalates the rest to Support Tickets with Slack alerts. Bot is "warm-voice" and intercepts the *first sight* of any new DM thread.
3. **Eve-of-Interview check-ins (1-10 score)** - auto DM the night before, capture replies (incl. Unicode superscript digits), surface results widget with Pre/Post & Academy/Private separations + 30-day sparklines + manual recovery + backfill.
4. **Private-Tier Videos board** (replaces Monday.com) - recorded answer review pipeline.
5. **Pre-warmed Google Drive document summaries** (Claude Sonnet 4.5 via Emergent LLM Key) using SWR caching.
6. **Coach Activity view** - daily review bars, weekly totals, over-allowance Calendly bookings, manual call logging.

## Architecture
- **Frontend**: React (CRA) at `/app/frontend/src` - pages under `pages/`, shadcn UI under `components/ui/`.
- **Backend**: FastAPI at `/app/backend` - routes under `routes/`, business modules at module root, MongoDB via `motor`.
- **Async polling**: Circle DM polling loop is an asyncio task launched at server startup (`/app/backend/circle_dm_poll.py`).
- **AI**: Claude Sonnet 4.5 via `emergentintegrations` library, Emergent Universal LLM Key.
- **Auth**: JWT-based admin login. Test creds in `/app/memory/test_credentials.md`.

## 3rd-Party Integrations
- Circle.so Admin + Headless API · Gmail OAuth 2.0 + Drive · Calendly · Wati WhatsApp · Slack webhooks/bot · Zapier · Monday.com (legacy, being phased out) · Claude Sonnet 4.5 (Emergent LLM Key).

## Key Mongo Collections
- `circle_dm_threads` - `{thread_uuid, coach_admin_email, last_seen_message_id, state, reset_at, sent_bodies, human_takeover_trigger}`
- `interview_eve_dms` - `{student_email, interview_date, score, sent_at, replied_at}`
- `manual_calls` - `{student_email, duration_min, source, created_at, created_by}`
- `tickets`, `circle_threads`, `documents`, `cohort_videos`, `students`, etc.

## Key API Endpoints (high-value)
- `GET /api/circle/bot/thread-trace` - DM bot thread simulator (diagnostic)
- `GET /api/circle/bot/diagnose` - Bot health & state
- `POST /api/interview-eve/backfill-scores` - Retroactive score scan
- `POST /api/today-calls/manual` - Off-Calendly manual call entry
- `GET /api/coach-activity` - Coach engagement metrics + daily bars

## What's Been Implemented (Major Milestones)
### Feb 2026 session
- ✅ Circle DM bot diagnostic suite (`thread-trace` API + "Diagnose a thread" UI in Settings)
- ✅ First-sight smart reply for new Circle DM threads
- ✅ "Trust & Re-arm" recovery for `human_takeover` resolution
- ✅ Eve-DM score capture executes before lookback guard; Unicode superscript regex (`⁹`) handled
- ✅ Backfill endpoint for missed Eve scores
- ✅ Eve check-ins widget: sent/replied/pending, sparklines, Pre/Post split, Academy vs Private tiers, manual recovery
- ✅ "Log extra call" dialog (off-Calendly) - counts as 1 event credit
- ✅ Daily-bars counts above bars + redesigned 28-day cohort view (weekly-totals row, week-break dividers, taller layout, hover tooltips)
- ✅ Circle DM escalation fix - subsequent replies after escalation forward to ticket as notes
- ✅ 🟣 `💬 N NEW` Circle badge on Ticket cards for unread Circle notes
- ✅ Timeline filter - Circle DM notes render as student messages (added `_circle_dm` to `STUDENT_AUTHOR_IDS`)

## Roadmap / Backlog
### P2 (Future)
- Pulse Score history + per-pillar drill-through
- WhatsApp template-message starter kit
- "✨ AI suggested reply" button on Tickets dashboard UI
- Settings UI for environment variables
- Enriched Linked Student card on tickets (interview date, at-risk, Pulse signal)

### Refactoring (technical debt)
- Break down `/app/frontend/src/pages/SupportTickets.jsx` (>2000 lines)
- Break down `/app/frontend/src/pages/Settings.jsx` (>2000 lines)

## Critical Operational Notes
- **Preview vs Production**: User auto-deploys to `https://ayci-dashboard.emergent.host` from GitHub. Both preview + production poll Circle simultaneously - if a Circle DM "vanishes" or state flips unexpectedly, suspect production scooping the message first. Test inside preview only.
- **Calendly accounting** is **event-based, not minute-based**. A 60-min mock = 1 event-credit.
- **`_circle_dm`** must stay in `STUDENT_AUTHOR_IDS` (SupportTickets.jsx) for Circle messages to render correctly on the ticket timeline.

## Test Files
- `/app/backend/tests/test_circle_dm_first_sight.py`
- `/app/backend/tests/test_parse_score.py`
- `/app/backend/tests/test_manual_call_credits.py`
