# AYCI Team Dashboard — PRD

## Original problem statement
Build a clean, modern team performance dashboard for AYCI Academy (a company helping doctors prepare for consultant interviews, ~10-person team, runs on EOS). Three views: Weekly Scorecard, Quarterly Rocks, Launch Dashboard. Plus Settings/Admin. JWT auth, admin + user roles. Notion-meets-financial-dashboard vibe, dark navy sidebar (#1A1F36) + teal (#0EA5E9).

## Architecture
- **Backend**: FastAPI + MongoDB (motor), JWT (PyJWT) auth via httpOnly cookies, bcrypt password hashing, all routes prefixed `/api`.
- **Frontend**: React 19 + React Router 7 + shadcn/ui + Tailwind + Recharts + Sonner. Manrope (display) + Inter (body) fonts. AuthContext with `withCredentials: true`.
- **Data model (MongoDB)**: `users`, `team_members`, `metrics`, `weekly_values`, `rocks`, `launches`, `launch_data`, `daily_registrations`.

## User personas
- **Admin (Tessa / Arub)** — full CRUD on team, metrics, rocks, launches, users.
- **Team member (user)** — view everything, update scorecard weekly values, update own rock status/notes, edit launch KPIs.

## Core (static) requirements
1. Weekly Scorecard: 13-week grid, 5 categories, owner avatars, editable cells, green/red goal highlighting, sparklines, summary ring with "X of Y on track".
2. Quarterly Rocks: grouped by owner, status pills (On Track/Off Track/Done) click-to-cycle, expandable notes, quarter selector, donut summary.
3. Launch Dashboard: per-launch KPI cards, stepped Good/Better/Best target bar, daily registrations line chart with previous launch overlay + cumulative, editable sales breakdown, launch-over-launch bar chart.
4. Settings: tabs for Team, Users, Metrics, Rocks, Launches (admin-only CRUD).
5. Auth: JWT cookie login, admin-only register endpoint, logout.

## Implemented (2026-02)
- ✅ JWT auth with bcrypt + httpOnly cookies (access_token 24h + refresh_token 7d).
- ✅ Admin auto-seeded on startup (`admin@ayci.com` / `Admin@2026`).
- ✅ 7 team members, 19 scorecard metrics (all 5 categories), 17 Q2 2026 rocks, 3 launches (NOV-25, FEB-26, APR-26) with sample daily registrations seeded.
- ✅ 4 weeks of sample weekly values seeded for immediate demo visibility.
- ✅ Weekly Scorecard: 13-week grid, category section headers, inline editing, goal-based green/red cells, 8-week sparklines, owner-filter chips, progress ring.
- ✅ Quarterly Rocks: grouped by team member cards, cycling status pills, expandable notes with save, quarter selector, donut summary.
- ✅ Launch Dashboard: launch selector, 4 KPI cards (2 editable), revenue-vs-target stepped bar with Good/Better/Best markers + tier badge, daily registrations line chart with prev-launch overlay + cumulative line, editable sales breakdown table, launch-over-launch bar chart.
- ✅ Settings with 5 tabs (Team, Users, Metrics, Rocks, Launches) — full CRUD for admin, read-only for user.
- ✅ Design: Navy sidebar + teal accent, Manrope+Inter fonts, soft green/red highlights per spec, professional doctor avatars from design agent.
- ✅ Backend 18/18 pytest passed; frontend e2e verified via screenshots.

## Prioritized backlog
**P1**
- Drag-and-drop re-ordering of metrics within a category (spec mentions but not yet).
- Quarter archiving (make old quarters read-only once new one is active).
- `/api/auth/refresh` endpoint (refresh_token is issued but unused — future extension).

**P2**
- Per-user rock-edit restriction (currently any authenticated user can update any rock; spec says "own rocks" — add ownership check if needed).
- Drag-and-drop / CSV export of scorecard.
- Real-time updates via WebSocket (for Monday live meetings).
- Email/Slack digest reminder before Monday meeting.

## Next tasks
- Wait for user feedback on design, data accuracy, and desired enhancements.
- Consider: Monday-morning auto-email to team summarising last week's scorecard + flagged off-track rocks (strong team-adoption hook).
