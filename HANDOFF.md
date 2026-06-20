# HANDOFF — session 19 Jun 2026

Pick-up notes after a big session. Everything below is **committed + pushed**;
Render auto-deploys `main`, so the live app already reflects it.

## TL;DR
Calendly booking zaps migrated off Monday; upgrade-bonus detection built + applied;
the early-access **grant button is fixed end-to-end** (single-space add via Circle
**Admin v1**); a Circle-cache staleness bug fixed; and the **Oksana → Coralie**
handover is all but done. Remaining work is **external** (Zapier/Circle/dashboard UI),
not code.

## Shipped this session (code, live on Render)
- **Early-access grant button fixed** — `circle_api.add_member_to_space` now uses Circle's
  **Admin v1** `POST /api/v1/space_members {space_id,email}` with **`CIRCLE_ADMIN_V1_TOKEN`**
  (Admin v2 only does whole-space-*group* adds = over-grant). Grant = single-space add + DM,
  records the grant, skips the DM if already a member. Confirmed working end-to-end.
- **Upgrade-bonus detection** (`upgrade_bonus.py`) — scans Stripe for launch upgrade purchases,
  grants a bonus 1:1, folds into the over-allowance check. **Applied: 7 students** (Justyna etc.).
  Admin: `GET /api/admin/upgrade-bonus/audit?refresh=true` then `/apply?apply=true`.
- **Over-allowance** — now counts a manual `extra_bonus_calls` + auto upgrade-bonus grants, so a
  legit 2nd bonus call no longer false-flags.
- **Circle cache bug** — Students list read an in-process 30-min cache the "Refresh Circle cache"
  button didn't reset; now reloads when the snapshot's `cached_at` changes (fixes "get on board
  first" lingering after a refresh).
- **Calendly zaps off Monday** — Round Robin (18/18b/18c), 15-min (15/16/16b), Mock (14/14b/14c);
  `book-call` + `update-by-email` hardened (combined-identity match, graceful no-match, uniform schema).
- **Mirror-emit bridge** — the Monday mirror now emits `column_changed` so Monday-trigger zaps can
  move to Catch Hooks.
- **Private video reply (Coralie handover, Option A)** — `routes/private_videos.py` posts as the
  configured sender (Coralie) first, falling back through the coaches to whoever's in the room.
- **Circle add-to-space diagnostic** — `GET /api/admin/circle/test-add-to-space` (how we found the v1 fix).

## Open to-dos (all external — do from any machine)
1. **Oksana → Coralie zap handover** — see `ZAPIER_OKSANA_HANDOVER.md`. Done: 72, 46, 47, 53, 17,
   8b, full Student-Wins family (First + FU1/2/3). **Left: 47b (if active), 54 (Grid, low priority),
   and a final Circle-app filter sweep.** Deadline = before Oksana's Circle account is deactivated.
2. **Coralie's Gmail reconnect** — "Connect Gmail" was spinning; almost certainly a blocked popup.
   Reload → allow popups → Connect once → sign in as `coralie@medicalinterviewprep.com`.
3. **Narges** — fresh private chat (manual): Coralie starts a Circle group chat (Coralie + Becky +
   Narges), then set her Private chat URL on the dashboard. (Old Oksana chat left to go quiet.)
4. **Miriam Saey Al-Rifai** — her NHS email is now on her record; re-run upgrade-bonus
   `audit?refresh=true` then `apply?apply=true` (should take applied 7 → 8).
5. **Anoop's Round Robin trigger** — confirm step-1 Event Type = `AYCI 1:1 (30 min)` (Becky + Charlotte done).
6. **60-min 1:1 round-robin** (`AYCI 1:1 (60 min)`) — has real bookings but **no book-call zap**, so those
   calls don't write a slot. Decide whether 60-min 1:1s count toward allowance; build a zap if so.

## Key facts / gotchas (so they're not re-derived)
- **Circle token types** (Circle → Settings → Developers): **Admin v2** = `CIRCLE_API_TOKEN` (member
  cache, chat, space-*group* adds); **Headless Auth** = `CIRCLE_HEADLESS_TOKEN` (per-member session by
  email via one parent token); **Admin v1** = `CIRCLE_ADMIN_V1_TOKEN` (the one that does **single-space**
  adds). All on Render, not in the repo.
- **Coralie's Circle login = `coralie.fairon@yahoo.co.uk`** (NOT her `@medicalinterviewprep.com` work
  email, which is *not* a Circle member). Same split-identity trap bites buyers (Miriam = NHS email).
- **Early-access via Monday** (fallback if the dashboard button ever fails): set the
  **"Trigger - Previous cohort access"** status column (`color_mksa60n6`) to **"Previous cohort access
  + Bonus Calls"** → fires zap #43 (adds to space + DM).
- **Spaces:** previous-cohort curriculum = `2529501` (AYCI Curriculum - April 26); bonus =
  `1944718` (Bonus Live Sessions).
- **Private chat config** (Settings → Private chat config): sender = Coralie; all 4 coaches verified on
  valid Circle emails (Coralie/Becky `becky.platt2@nhs.net`/Arub `arubyousuf89@gmail.com`/Tessa).
- **Auto-commit + push** convention; Render redeploys on push (brief 502 during the bounce is normal).

## Where the detail lives
`ZAPIER_AUDIT.md` (master Monday-retirement plan) · `ZAPIER_NEXT_BATCH.md` (Calendly batches) ·
`ZAPIER_OKSANA_HANDOVER.md` (Oksana zaps) · `CALENDLY_FLOW.md` (Calendly→dashboard map) ·
`MONDAY_REPLACEMENT_SPEC.md` · `SUPPORT_TEAM_SOP.md` / `TEAM_SOP.md`.
