# SOP — Private Chats (private-tier students)

_For the AYCI team. How to check who has / needs a private coach chat, spot students
whose DMs are off, and create the chats. Last updated 2026-06-14._

## Background (30 seconds)

Every **private-tier student** (Private Plus, VIP, Boost & Go, Boost & Go Plus) should
have a **coach group chat** in Circle where they get video feedback and can ask questions.
The chat is normally created automatically when they join Circle. This SOP is how you
**catch the ones that slipped through** and fix them.

Two places do the work, both in the dashboard:
- **Students (DB)** — the at-a-glance list with flags.
- **Settings → Integrations → "Private chat setup"** — the tools to audit Circle and create chats.

> ⚠️ Trust the **dashboard** for tier / Boost & Go status, **not** Circle tags — Circle's
> tags are unreliable (a member can show up under the wrong tag).

---

## 1. Who doesn't have a private chat set up yet?

**Quickest view — Students (DB):**
1. Left menu → **Students (DB)**.
2. Tick the **"⚠ Needs setup"** filter at the top.
3. This shows every current private-tier / Boost & Go student who is **missing their
   private chat link** (or their video allowance, or is blocked — see §2). Each row has a
   **⚠ Setup** badge; the **Private chat** column shows **"— missing"**.

Use this for the day-to-day "who still needs sorting" list.

**Authoritative view — the Circle audit** (catches cases the list above can miss, e.g. a
student who has a *dead* chat link on their row):
1. **Settings → Integrations → "Private chat setup"** card.
2. Scroll to **"Backlog audit — no group chat in Circle"** → click **Run audit**.
3. It checks Circle directly and lists every private-tier student who is **not in any
   coach group chat**. Each row has a **Create chat** button (see §3).

> Use **Needs setup** for a fast daily scan; run the **audit** when you want the definitive
> "who genuinely has no chat in Circle" list.

---

## 2. How to tell if someone's DMs are off

Circle does **not** expose a "DMs off" setting anywhere — so we surface it a different way.

When a chat can't be created **because the student has switched their Circle DMs off**, they
get flagged with an orange **"Awaiting DMs"** badge:
- **Students (DB)** → they appear under **Needs setup** with the orange **Awaiting DMs** badge
  (instead of, or alongside, "⚠ Setup").

**To fix an "Awaiting DMs" student:**
1. Message the student: ask them to **turn their Circle DMs back on**
   (*Circle → their profile/avatar → Settings → Messaging → allow direct messages*).
2. Once they confirm, **create their chat** (see §3).
3. **Clear the flag:** open the student in Students (DB) → **Edit** → empty the
   **"Private chat status"** field → Save. (The dashboard also clears it automatically when
   it successfully creates the chat.)

**Suspect someone but they're not flagged?** Try creating their chat (§3). If their DMs are
off, the attempt fails and they get the **Awaiting DMs** flag — which both confirms it and
puts them on the list to chase.

---

## 3. Seeing who's yet to be allocated a chat — and creating one

**Settings → Integrations → "Private chat setup"** card:

- **"Ready to create"** list — private-tier students who are **on Circle with no chat**, ready
  to be set up. Each shows their tier and how they were matched.
- Click **Create chat** on a student → the dashboard creates their coach group chat (with the
  coaches: Tessa, Arub, Coralie, Becky), posts the welcome message for their tier, and links it
  on their row.
- The **Backlog audit** (§1) is the broader version — it also catches students with a *dead*
  chat link.

**If "Create chat" is greyed out / disabled, it's one of:**
- **"no <tier> template"** next to the student → that tier's welcome message hasn't been set.
  Add it: same card → **Welcome message per tier** → pick the tier tab → paste the message → Save.
  *(Status: Private Plus, VIP, Boost & Go Plus are set; **plain Boost & Go is still to be added**.)*
- The coach config isn't complete (every coach needs their Circle email + one set as the sender).

---

## Quick reference

| You want to know… | Where | What you see |
|---|---|---|
| Who still needs setting up (daily) | Students (DB) → **Needs setup** filter | **⚠ Setup** badge · "— missing" chat |
| Who genuinely has no chat in Circle | Private chat setup → **Run audit** | the **no-chat** list + Create buttons |
| Who's ready to have a chat made | Private chat setup → **Ready to create** | list + **Create chat** |
| Whose DMs are off | Students (DB) → Needs setup | orange **Awaiting DMs** badge |
| Create a chat | Private chat setup → **Create chat** | chat made + welcome posted + row linked |
| Clear an "Awaiting DMs" flag | Students (DB) → row → **Edit** | empty **Private chat status** → Save |

## Good to know

- **Existing chats are never touched / duplicated.** Creating from the dashboard only ever
  makes a chat for someone who has none — it never spawns a second thread, and video replies
  keep going to the student's existing chat.
- **Regular Boost & Go welcome message** still needs adding before B&G (non-Plus) students can
  have chats created — until then they'll show "no Boost & Go template".
- Access: these pages are **admin / students-board** only.
