# Dashboard — migration status & to-dos

_Portable companion to `ZAPIER_AUDIT.md` (which has the per-zap detail). Last updated 2026-06-09._

## Where we are

The dashboard is a **mirror of the Monday "Academy Members" board** (15-min sync). Retiring Monday means removing every dependency — zaps that **write** to Monday, and the **new-signup path** that creates rows there — then turning the mirror off.

**Every migration pattern is now built & proven in production:**
- `POST /api/students-db/update-by-email` — replaces Monday `Get Items + Update Item`. Returns `previous_values` for read-modify-write zaps.
- `POST /api/students-db/lookup-by-email` — read a student (scalar fields + named Monday columns).
- `POST /api/students-db/book-call` — `{email, coach}` → fills the next 1:1 Call slot (`Booked - <Coach>`); replaced the AI-by-Zapier slot picker.
- `POST /api/students-db/intake` — upsert a student by email; **mirror reconciliation** merges the `auto:` row when the Monday row syncs (no duplicates, no delay).
- **Outbound dispatcher** — fires `column_changed` to subscribers when a dashboard-owned field changes. Admin UI at `/webhooks` (admin-only). Only fires on **dashboard-originated** changes.
- `POST /api/toolkit/access` — `{email}` → which Kajabi add-ons they bought (gates tools.medicalinterviewprep.com).

**Migrated so far (write-side → dashboard):** Milestones 1–5, Mock Interview ×3, 15-min call ×3 ✅ · 8c Boss-badge (Path A) & 1:1 Round Robin ×3 🟦 Phase-1 (Monday safety-net steps still in place) · **AYCI signup create paths → `intake` ✅ (the P0 — new students now land in the dashboard directly).**

## To-dos

### Immediate (this week)
- [ ] **Verify new signups** land in Students (DB), then **remove the 3 Monday `Create Item` steps** from "[AYCI JUNE-26] Signups to Monday Board (OD)" (first real "Monday does less" step).
- [ ] After ~1wk verify: **remove the Monday safety-net steps** from the 15-min-call zaps; do **Round Robin Phase 2** (delete Monday/AI/Paths machinery → single `slot`-empty Filter → Fallback).

### Coralie batch (when she's back — week of 2026-06-08)
- [ ] **Circle:** Coralie connects her Circle account in Zapier (admin/mod rights needed) → **publish 8b** (first dispatcher consumer, catches `boss_badge`) → switch the other `(Oksana)` zaps' connections to Coralie **before Oksana's accounts are deactivated**.
- [ ] **Gmail:** Coralie re-connects her inbox via **My profile → Connect Gmail** (her token is expired → the lone `errors: 1` on gmail sync). Re-connect refreshes it + assigns ownership to her.

### Per-launch (recurring) ⚠️
- [ ] **Each new cohort:** update the hardcoded **`cohort_joined: "June 26"`** literal in the 3 signup `intake` POSTs (Academy/PP/VIP create paths). Cohort dates follow from the step 4/5 formatters automatically; only `cohort_joined` + `tier` are hardcoded.

### Later (the rest of retiring Monday)
- [ ] **Remaining write-side zaps → `update-by-email`** — cohort-lifecycle / Kit- / Circle-triggered ones, **plus the 2 legacy-upgrade signup paths** (need Tier End Date / In Active Cohort / Legacy added to the dashboard first; mirror covers them meanwhile).
- [ ] **Outbound dispatcher rollout** to the ~12 Monday-*triggered* zaps (after 8b proves it). Caveat: only fires on dashboard-originated changes — needs the triggering edits to happen in the dashboard (or a mirror-emit bridge).
- [ ] **AYGI / waitlist signups → `intake`** (AYGI deferred to the 2027 cohort).
- [ ] **Final cutover:** turn off the Monday→Mongo mirror → archive the board.

## Key reference

- **Frontend:** https://ayci-dashboard-nfiw.vercel.app (Vercel) · **Backend:** https://ayci-dashboard.onrender.com (Render; env vars in Render UI — `backend/.env` is gitignored). Hosting + LLM are off Emergent.
- **Secrets:** `ZAPIER_WEBHOOK_SECRET` (in every migrated zap's `X-Webhook-Secret`) · `TOOLKIT_ACCESS_SECRET` (toolkit site's server-side call).
- **"Needs setup" flag** = current private tier (Private Plus / VIP / Boost & Go, incl. "Upgraded" B&G) **and not a Boss** **and not** marked "not needed" **and** missing a private chat link OR video allowance. Deprecated tiers (Platinum/1:1/legacy) excluded.
- **Video allowance map:** Private Plus 15 · VIP 30 · Boost & Go 5 · Boost & Go Plus 10. ("Used" column counts actual private-video submissions.)
- **Webhook Subscriptions** = admin-only. **Students (DB) / Student Lookup** = `students` board permission (manage in Settings → Users). The personal **Connect Gmail** is on every user's **My profile**.
