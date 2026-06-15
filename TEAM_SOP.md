# AYCI Dashboard — Team SOP

_How the team runs the day-to-day on the dashboard: private chats, video allowances, interview-date changes, support tickets, and how it all fits together. Written so anyone on the team can follow it without needing to know any code. Last updated 2026-06-15._

---

## 0. What this dashboard is (read this first)

The dashboard (the AYCI web app) is the team's single source of truth for students. It used to all live on the Monday.com "Academy Members" board; the dashboard now does that job and more. A few things to hold in your head:

- **It mirrors the Monday board** and refreshes every ~15 minutes — so a change on Monday shows up here within 15 min, and some things (interview dates, private-chat status, Boost & Go) are now **owned by the dashboard** and "pinned" so a Monday sync can't overwrite them.
- **Trust the dashboard, not Circle tags**, for a student's tier or Boost & Go status. Circle's member tags are unreliable (people show under the wrong tag). The dashboard is authoritative.
- **Access is by role.** Most of these tools are visible to **admins** and anyone on the relevant **board** (e.g. the "students" board, the "tickets" board, the "refunds" board). If you can't see a page or button described here, you probably need that board added — ask Tessa (Settings → Users).

**The main pages you'll use:**
| Page | What it's for |
|---|---|
| **Students (DB)** | The master list of students with flags, filters, and inline editing. |
| **Upcoming Interviews** | Who's interviewing soon, with their call / video usage. |
| **Support Tickets** | Incoming questions (Circle DMs + WhatsApp) to action. |
| **Settings → Integrations** | Setup tools, including **Private chat setup**. |
| **Refunds** | Refund tracking (Stripe-sourced). |

---

## 1. Private chats (private-tier students)

Every **private-tier student** (Private Plus, VIP, Boost & Go, Boost & Go Plus) should have a **coach group chat** in Circle, where they get their video feedback and can ask questions. The chat is normally created automatically when they join Circle. This section is how you **catch the ones that slipped through** and fix them.

Two places do the work, both in the dashboard:
- **Students (DB)** — the at-a-glance list with flags.
- **Settings → Integrations → "Private chat setup"** — the tools to audit Circle and create chats.

### 1a. Who doesn't have a private chat yet?

**Quick daily view — Students (DB):**
1. Left menu → **Students (DB)**.
2. Click the **"⚠ Needs setup"** filter at the top.
3. This shows every current private-tier / Boost & Go student who is **missing their private chat link** (or their video allowance — see §2). Each row shows a **⚠ Setup** badge; the **Private chat** column shows **"— missing"**.

**Authoritative view — the Circle audit** (catches cases the quick view can miss, e.g. a student with a *dead* chat link on their row):
1. **Settings → Integrations → "Private chat setup"** card.
2. Scroll to **"Backlog audit — no group chat in Circle"** → click **Run audit**.
3. It checks Circle directly and lists every private-tier student who is **not in any coach group chat**. Each row has a **Create chat** button.

> Use **Needs setup** for the fast daily scan; run the **audit** when you want the definitive "who genuinely has no chat in Circle" list.

### 1b. How chats get set up (and creating one)

In **Settings → Integrations → "Private chat setup"**:

- **"Ready to create"** — private-tier students who are on Circle with no chat, ready to go. Each shows their tier and how they were matched.
- Click **Create chat** on a student → the dashboard creates their coach group chat (with the coaches: **Tessa, Arub, Coralie, Becky**), posts the **welcome message for their tier**, and links it on their row.

**If "Create chat" is greyed out**, it's one of:
- **"no `<tier>` template"** next to the student → that tier's welcome message hasn't been set. Add it in the same card → **Welcome message per tier** → pick the tier tab → paste the message → Save.
  *(Status: Private Plus, VIP, and Boost & Go Plus are set; **plain Boost & Go still needs its message pasted**.)*
- The coach config isn't complete (every coach needs their Circle email, with one set as the sender — currently **Coralie**).

> **Existing chats are never touched or duplicated.** Creating from the dashboard only ever makes a chat for someone who has none — it never spawns a second thread, and video feedback keeps going to the student's *existing* chat. (This matters because some older students' chats were created by Oksana; those are detected and left alone.)

### 1c. What happens when a student's DMs are off (closed)

Circle does **not** expose a "DMs off" setting anywhere — so a chat simply **can't be created** for a student who has switched their Circle direct messages off. We surface this so it doesn't fail silently:

- When creation fails because DMs are off, the student is flagged with an orange **"Awaiting DMs"** badge and appears in **Needs setup**.

**To fix an "Awaiting DMs" student:**
1. Message the student and ask them to **turn their Circle DMs back on** (*Circle → profile/avatar → Settings → Messaging → allow direct messages*).
2. Once they confirm, **create their chat** (§1b).
3. **Clear the flag:** Students (DB) → open the student → **Edit** → empty the **"Private chat status"** field → Save. (It also clears automatically when a chat is successfully created.)

**Suspect someone but they're not flagged?** Just try creating their chat. If their DMs are off, the attempt fails and they get the **Awaiting DMs** flag — which both confirms it and puts them on the chase list.

---

## 2. Missing video allowances or chat links

A private student's row in **Students (DB)** has two columns that commonly need attention, both surfaced by the **⚠ Needs setup** filter:

- **Videos** — shows `used / allowance` (e.g. `2 / 6`). Turns red when they've hit their limit.
- **Video allowance** column — the expected number for their tier. You'll see:
  - a green number → set correctly,
  - **"— / 6"** in amber → **missing** (no allowance set, expected 6),
  - **red "4 / 6"** → set but **doesn't match** the expected value for their tier (review it).
- **Private chat** — a link if they have one, or **"— missing"** if not (covered in §1).

**To fix missing allowances in bulk:**
1. Students (DB) → **Set missing video allowances** button.
2. It lists every student with **no** allowance set and shows the expected value for each tier.
3. Apply → it sets each missing one to the tier's expected value. **It does not touch** existing numbers or mismatches — those you review individually via the row's **Edit**.

> Mismatches (red) are deliberately left for a human — they usually mean something tier-specific, so check before changing.

---

## 3. Interview-date changes (when a student reschedules)

When a student's interview moves, they submit the **Tally interview-date form** again with the new date. The dashboard treats **Tally as the source of truth** and always uses their **most recently submitted** date.

**How it works automatically:**
- A scheduled job (twice each weekday, early morning and evening) reads everyone's latest Tally submission and updates each student's **interview date** in the dashboard. The new date is **pinned**, so the next Monday sync won't overwrite it back to the old date.
- The shared **AYCI Interviews Google Calendar** is kept in step automatically: each student has **one** calendar event at their current date. If they reschedule, the old event is removed and the new one created — so the calendar never shows a stale/duplicate interview.

**If you need it to update right now** (don't want to wait for the scheduled run):
1. **Upcoming Interviews** page → **"Reconcile dates from Tally"** button.
2. It pulls the latest Tally dates and updates the dashboard immediately. (It's safe to run anytime; running it twice in a row changes nothing the second time.)

**What you'll see:** Student Lookup and Upcoming Interviews show the **latest Tally date**, not the old Monday column. So if a student says "I moved my interview and submitted the form," their new date should be reflected after the next run (or after you click Reconcile).

---

## 4. Support tickets (Circle DMs + WhatsApp)

The **Support Tickets** page collects questions from two sources. **The dashboard never replies on its own** — tickets are there for a human to action.

### 4a. Circle DMs
When a student sends a Circle DM to one of the coaches (Tessa, Becky, Coralie, Oksana) and it **hasn't been answered**, the dashboard automatically creates a ticket for Coralie to pick up. Notes:
- It only **reads** DMs — it can't and won't send any reply in Circle. Replying still happens in Circle by a human as normal.
- Interview-eve "night before" threads are left alone (handled by the score-capture flow).
- Automated Circle accounts (e.g. **"Do Not Reply Bot"**) are ignored — they don't create tickets.

### 4b. WhatsApp (WATI)
Incoming WhatsApp messages also become tickets. During busy launch periods, lots of people send identical short replies ("Send it!", "I've already joined!", etc.) that don't need a response.

- **To stop a repeated message from making tickets:** open one such ticket → **🔕 "Ignore future messages with this wording"**. From then on, any incoming WhatsApp message with the **same wording** is skipped (no ticket), and it also closes any open tickets that already match.
- **The "WhatsApp · errors" badge** at the top of Support Tickets just means the last WhatsApp sync hit a hiccup (usually a temporary connection/token issue). Hover it to see the detail. It does **not** stop tickets from coming in.

---

## 5. Boost & Go flagging (good to know)

Some students who bought **Boost & Go** weren't showing as B&G in the dashboard, because that flag mirrored a Monday column that didn't always flip when they purchased. This has been reconciled against Stripe purchases and backfilled, and new purchases now flag the dashboard directly.

If you ever suspect a B&G buyer isn't flagged: tell Tessa — there's an admin audit (against Stripe) that can be re-run anytime to catch stragglers. A handful of buyers can't be matched automatically because they used a **different email** on Kajabi vs Circle (see the glossary) — those need a manual look.

---

## Glossary / good to know

- **Tier** — Private Plus (PP), VIP, Boost & Go (B&G), Boost & Go Plus. "Private tier" = any of these; they get coach group chats and video feedback.
- **The dual-email problem** — a student can sign up on Kajabi with one email and use a different one on Circle. When the two don't match, automatic matching breaks (a chat may never get created, or a purchase won't flag). The dashboard matches on **both** emails where it can; truly mismatched ones need a human to reconcile.
- **"Pinned" fields** — interview date, private-chat status, and Boost & Go are owned by the dashboard and protected from being overwritten by the Monday sync.
- **Who's who** — Coaches: Tessa, Arub, Becky, Oksana (+ others). **Coralie = customer support** (she handles tickets), and she's the "sender" for new private chats.

## Quick reference

| You want to… | Where | What you see / do |
|---|---|---|
| See who still needs setting up | Students (DB) → **⚠ Needs setup** | ⚠ Setup badge · "— missing" chat · amber/red video allowance |
| Confirm who has no chat in Circle | Private chat setup → **Run audit** | the no-chat list + **Create chat** |
| Create a private chat | Private chat setup → **Create chat** | chat made + welcome posted + linked |
| Handle a "DMs off" student | Students (DB) → **Awaiting DMs** badge | ask them to re-enable DMs → create chat → clear status |
| Fix missing video allowances | Students (DB) → **Set missing video allowances** | bulk-set the missing ones to tier value |
| Update a rescheduled interview now | Upcoming Interviews → **Reconcile dates from Tally** | pulls latest Tally date immediately |
| Action a question | Support Tickets | reply in Circle/WhatsApp as normal; tickets are the queue |
| Silence repeated WhatsApp spam | a WhatsApp ticket → **🔕 Ignore future messages with this wording** | future identical messages skipped |
