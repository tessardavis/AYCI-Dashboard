# AYCI Dashboard - Support Team SOP (Coralie & Megan)

A practical guide to the tasks you'll do most in the dashboard: **setting up private-tier private chats** (and finding the ones that are missing), **giving early-interview students catch-up access** (previous cohort + Sunday group calls), and a tour of the **other boards** you have.

Dashboard: **ayci-dashboard-nfiw.vercel.app** · log in with your own account. The left sidebar is your menu - you only see the boards you've been given access to. If a board you need is missing, ask Tessa to enable it (and do a full page reload / re-login after she does, or it won't show up).

> **Golden rule:** most weird-looking data (a student who's "missing", "not on Circle", or shows the wrong details) comes down to an **email mismatch** between Monday, Kit and Circle. When in doubt, check the email - and if it still doesn't make sense, flag it to Tessa rather than guessing.

---

## 1. Private-tier private chats - setup & finding missing ones

Every private-tier student (Private Plus, VIP, and active Boost & Go) gets a **private group chat on Circle** with the coaches. This is where their video-reply feedback and coaching happen, so everyone needs one.

### Finding who's missing
**Students (DB)** → tick the **"⚠ Needs setup"** filter. This shows private-tier / B&G students who don't have a private chat link yet. Each row shows an **On Circle?** status under "- missing":

- **`on Circle · needs chat`** - they're on Circle, they just need a chat created. ✅ Easy - create it (below).
- **`not on Circle`** - their email doesn't match any Circle member. Almost always **a wrong/typo'd email** or they **haven't joined Circle yet**. Fix the email first (Edit → correct it), or chase them to join - *then* create the chat.

### Creating a private chat
Go to **Settings → Integrations → "Private chat setup"**. You'll see a **Ready** list of private-tier students who need a chat. Click **Create chat** next to a student:
- It creates the Circle group chat, adds the coaches, posts the welcome message, and records the link on their record. Takes up to ~1 minute - the list updates as it finishes.
- If it moves them to **"Awaiting DMs"**, that student has Circle DMs switched off - they need to enable DMs before a chat can be made. Chase them, then retry.
- **Run audit** finds private-tier students who already *have* a coach chat in Circle but whose link was never recorded - it links those up automatically.

### Linking a chat that already exists
If a student already has a chat (you can see it in Circle) but the dashboard says "missing", open them in **Students (DB) → Edit**, paste the chat's URL into **"Private chat URL"**, and Save. (The link looks like `https://ayci-academy.circle.so/messages/<long-id>`.)

### If a student genuinely shouldn't get one
Click **"Not needed"** on their row (e.g. they've landed a job / aren't really private-tier). They drop off the setup list. You can add a short reason.

> Don't manually create chats in Circle by hand unless Tessa asks - use the dashboard so the link gets recorded.

---

## 2. Previous-cohort & Sunday-coaching-call allocation

**The goal:** students who have interviews **soon** - and therefore won't get the benefit of the full cohort before their interview - should be given access to the **previous cohort** (its curriculum + recorded sessions) and/or the **Sunday coaching calls**, so they can prepare in time.

### Who's on the list
On **Students (DB)** there are **two filter chips**:
- **⏱ Early - to allocate** - students who need access but don't have it yet. *Your to-do list.*
- **✓ Early - access given** - students who've already been sorted.

These include **new June-26 students** and **"in-between" students** (who joined between cohorts) who have an interview **before 19th July (end of Week 3)**. (Legacy/returning students who've already done the course are not included.)

**It stays up to date automatically:** if a student gets a soon interview date and submits the **Tally interview-date form**, they'll be added to this list on their own (no manual step).

### Join the cohort first
We **don't** grant this access until the student has actually **joined the current cohort on Circle** - joining the cohort is the priority. So on the to-allocate list, each row shows one of:
- **⏱ ready to grant** - they're in the cohort on Circle → go ahead.
- **⏱ get on board first** - not in the cohort yet → chase them to join Circle / the cohort first, *then* grant.

### How to allocate
Open the student → **Edit** → at the bottom (**Early-interview access**) click one of:
- **Previous Cohort** - adds them to the previous cohort's curriculum space.
- **Sunday Group Calls** - adds them to the Sunday coaching calls (Bonus Live Sessions space).
- **Both** - does both.

This adds them to the Circle space(s) **and sends them a DM** letting them know. You'll get a confirmation, and the row flips to **"✓ Access given"**.

### If they're not in the cohort yet
If you try to allocate to someone who **isn't yet in the Circle cohort**, the dashboard **won't let you** - it shows a message explaining why (they need to join the cohort first). Nothing is sent or changed. Get them on board, then come back and grant.

---

## 3. The other boards - what each is for

You'll have a subset of these (whatever Tessa enabled). Quick orientation:

- **Cohort Dashboard** - live health-check of a cohort: headcount, who's joined Circle, engagement, and a "Still to join Circle" chase list. *(There's a separate detailed guide: `COHORT_DASHBOARD_GUIDE.md`.)*
- **Upcoming Interviews** - students with interviews coming up (next 7-14 days), split by Academy vs private tier, with their call/video allowance usage. Also shows the **Eve check-ins** (the confidence-score DMs sent the night before each interview).
- **Student Lookup** - search any student by name/email to see their full profile: tier, milestones, allowance usage, engagement. Your go-to for "what's the situation with this person?"
- **Students (DB)** - the editable master list of all students (mirrors the Monday Academy Members board). This is where you do the setup + early-access tasks above, fix emails/details, and filter (Needs setup, Early interview, Allowance mismatch, Refunded, Boost & Go). Edits here "pin" and won't be overwritten by the Monday sync.
- **Students at Risk** - students who look disengaged / behind, so they can be nudged.
- **Coach Activity** - tracks coach engagement in the cohort spaces (how responsive coaches are).
- **Spotlight Coaching** - the spotlight/coaching feature workflow.
- **Cohort Leaderboard** - student engagement ranking for the cohort (gamification).
- **Support Tickets** - incoming support requests to work through.
- **Refunds** - refunds recorded from Stripe, for tracking/following up.
- **Circle DM Bot** - settings + playbook for the bot that watches Circle DMs and routes/escalates them.

If you open a board and aren't sure what a number or column means, ask Tessa - better to check than assume.

---

## When to escalate to Tessa

- A student is **"not on Circle"** and their email looks correct (not a typo) - possible deeper mismatch.
- **Create chat** keeps failing or a grant throws a red error.
- Numbers on a board look clearly wrong for a specific person.
- Anything involving **Settings you can't see** (coach config, cohort config, user permissions) - those are admin-only.

---

*Questions or something not covered here? Ask Tessa and we'll add it to this guide.*
