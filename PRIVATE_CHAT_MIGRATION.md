# Private-chat creation → dashboard-native (Route 2)

_Plan for retiring the "Private Chat … when they join Circle" zaps (46 Legacy
Upgrades / 47 VIP+PP / 53 Boost & Go / 54 AYGI) by having the dashboard create
the coach group chats itself. Companion to `ZAPIER_AUDIT.md` + `DASHBOARD_STATUS.md`.
Drafted 2026-06-09._

## Why (root cause it fixes)

Today: student joins Circle → an "On Circle" zap matches them back to their row
**by email** and flips a Monday status column → that change triggers the private-
chat zap, which creates the coach group chat. If the student joined Circle under
a **different email** than they signed up with on Kajabi, the match fails,
`circle_email` is never written, and the chat is never created. (See the
`circle-email-gaps` detector + Link panel — the manual version of this.)

Route 2 makes the dashboard own detection + matching, matching on **either**
email (and strong name), so the dual-email case stops silently dropping students.

## Model: periodic reconciliation (not an event)

Fits the existing architecture (15-min mirror sync, Circle-cache refresh,
interview-eve cron). A job sweeps every **current private-tier / active B&G**
student who is **not** Boss, **not** `setup_not_needed`, and has **no
`private_chat_url`**. Per student:

1. **Resolve Circle identity** from `circle_members_cache` — match on `email` OR
   `circle_email` OR strong fuzzy name (reuse `student_lookup.name_search` +
   the gaps-detector logic). Matched under a different email → write
   `circle_email` (the dual-email fix). Not on Circle → skip, retry next run.
2. **Resolve coach(es)** from the coach config (below).
3. **Create/find the group chat** (coach[es] + student) via Circle Headless
   `POST /messages` — generalize `interview_eve_dm._ensure_dm_chat_room` into
   `circle_api.create_group_chat(admin_email, member_ids, name)` (`kind: "group"`
   + name). _Contract detail to verify live: exact `kind` value + group perms._
4. **Tag the member** in Circle (the onboarding tag the zaps apply).
5. **Write back** (pinned in `dashboard_edited_fields`): `circle_email`,
   `private_chat_url`, `private_chat_coach`, `private_chat_created_at`.
6. **Post the welcome message** into the chat (templated).
7. **Slack alert** to the team channel.
8. **Idempotency / no-duplicate guard:** in Circle, a group DM's identity *is*
   its member set — you can't add/remove people, and "find-or-create" with a
   different roster makes a **new** room. So creating a chat for a student who
   already has one spawns a confusing duplicate. Guards, in order:
   - `private_chat_url` present on the row ⇒ skip outright.
   - Before creating, **check Circle** for an existing coach group chat with this
     student (list a resident coach's — e.g. Coralie's — group threads, look for
     one whose participants include the student). Found ⇒ record that URL, don't
     create.
   - Residual case (chat exists but neither the row nor the Circle check finds
     it) is caught by **Phase 0 being manual + preview** — a human confirms each
     creation before it happens.
   This is also what makes it safe to run in **parallel** with the live zaps.

## Coach assignment (resolved 2026-06-09)

It's the **same coaches for every student** — the Zapier "coach list" table was
just an easy place to edit who they are, occasionally. So we port it as an
**admin-editable dashboard config** (in `settings_store`, surfaced as a Settings →
Integrations card like the others): the list of coach Circle identities added to
every private chat, with the data shape allowing optional per-tier overrides later
(defaults to the one shared list).

**Each chat = one student + several coaches.** Coach list for **new** chats
(2026-06-09): **Tessa, Arub, Coralie, Becky** — **Oksana dropped** (she's being
offboarded). One coach is the designated **owner / welcome-DM sender** (their
Circle token creates the room + posts the welcome message) — proposed **Coralie**
(the OD/onboarding role the zaps ran under); TBC.

**Existing chats are left untouched** — Oksana stays in the old ones. This is
harmless on two counts:
- **Video routing is decoupled from chat membership.** "Send to Circle" sends
  each voicenote to `destination = that student's own `private_chat_url``
  (`routes/private_videos.py`), keyed by *which student*, never by *who's in the
  chat*. A mixed state (old chats with Oksana, new without) needs no special
  handling.
- **You can't remove someone from a Circle group DM anyway** — membership defines
  the room's identity, so any roster change spawns a *new* chat and confuses
  students. So there is **no** "remove Oksana" sweep; old chats are permanent
  as-is.

## New pieces

- `backend/private_chat_setup.py` — the reconciliation job + per-student function.
- `circle_api.create_group_chat(admin_email, member_ids, name)` — generalized from
  the existing 1:1 room helper.
- Coach config in `settings_store` + a Settings card to edit it.
- Endpoints: `GET /api/students-db/private-chat/preview` (dry-run, no writes),
  `POST .../private-chat/run` (admin, sweep), `POST .../{id}/create-private-chat`
  (per-student manual trigger).
- Cron registration in `server.py` alongside the other periodic jobs.
- Frontend: grow the Circle-email-gaps panel into a "Private chat setup"
  preview / run / per-row create.

## Reuse

`circle_api` (token, room create, post message) · `circle_members_cache` +
`student_lookup.name_search` (matching) · `settings_store` (Slack webhook, coach
config, templates) · the needs-setup flag predicates in `routes/students_db.py`.

## Rollout (safe, parallel)

- **Phase 0** — dry-run preview + per-student manual button only (no cron).
  Verify a handful by hand against real students.
- **Phase 1** — admin "run all," still parallel with the zaps; idempotency
  prevents double-creation.
- **Phase 2** — once proven ~1 week, switch off zaps 46/47/53/54.

## Open items to confirm before/while building

- [ ] Coach config: the actual coach name(s) + which is the DM-sender owner.
- [ ] Circle group-chat API: verify `kind` value + that the coach token has
      group-create perms (mechanism confirmed; exact contract to test live).
- [ ] Exact Circle **tag name(s)** + any **space adds** the current zaps apply.
- [ ] Group-chat **name** format (copy from the live zaps).
- [x] **Welcome message is per-tier** (Tessa screenshot 2026-06-09). It's a rich
      message with the tier name, a 1:1 Calendly link, the video-allowance count,
      a Tally upload link with name/lastname/email pre-filled, and a personalised
      prep-timeline link — and the old zaps had a path per tier, so wording/links
      vary by audience. Modelled as **per-audience templates** (`private_plus` /
      `vip` / `boost_and_go` / `boost_and_go_plus`) in the coach config, with
      placeholders `{first_name} {last_name} {full_name} {email} {tier}
      {video_allowance}` substituted at send. **Private Plus seeded** from the
      screenshot; a student whose audience has no template is BLOCKED from create
      (won't send the wrong tier's message). **Still needed from Tessa:** the
      message text for VIP / Boost & Go / Boost & Go Plus (and whether the
      timeline/Calendly links differ per tier).
- [ ] Confirm whether **Boost & Go** splits further by *presentation /
      no-presentation* (zap 53 had 4 paths) — if so, add those audience keys.
- [ ] One coach per chat vs several (config holds a list either way).
