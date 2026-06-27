import { useState } from "react";
import { BookOpen, MessageCircle, Gift, Phone, Users, Rocket, Award, CheckCircle2, Clock, Loader2, Send } from "lucide-react";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import BonusCallSummary from "@/components/BonusCallSummary";
import PrivateCallSummary from "@/components/PrivateCallSummary";
import BossChaseSummary from "@/components/BossChaseSummary";

// In-dashboard process docs the whole team can read. Add a process by adding an
// entry here. The canonical/source copy also lives in PROCESSES.md in the repo.
const PROCESSES = [
  { slug: "bonus-calls", title: "Bonus calls", status: "ready", body: BonusCallsDoc },
  { slug: "private-tier-calls", title: "Private Tier calls", status: "ready", body: PrivateTierCallsDoc },
  { slug: "private-chat", title: "Private chat", status: "ready", body: PrivateChatDoc },
  { slug: "boost-and-go", title: "Boost & Go", status: "ready", body: BoostAndGoDoc },
  { slug: "boss-testimonials", title: "Boss Badge & testimonials", status: "ready", body: BossTestimonialsDoc },
  { slug: "refunds", title: "Refund status", status: "soon" },
];

export default function Processes() {
  const ready = PROCESSES.filter((p) => p.status === "ready");
  const [active, setActive] = useState(ready[0]?.slug || PROCESSES[0].slug);
  const current = PROCESSES.find((p) => p.slug === active);
  const Body = current?.body;

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="processes-page">
      <div>
        <div className="text-[11px] font-display font-semibold tracking-[0.25em] uppercase text-[var(--ayci-teal)]">
          Team
        </div>
        <h1 className="text-4xl font-display font-bold text-[var(--ayci-ink)] mt-1 flex items-center gap-2">
          <BookOpen className="w-8 h-8 text-[var(--ayci-teal)]" />
          Processes
        </h1>
        <p className="text-[var(--ayci-ink-muted)] text-sm mt-1 max-w-2xl">
          How each Academy process works - what's automated, where it lives, and what the team
          needs to do. Pick a process to read it.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-6">
        {/* Process list */}
        <nav className="space-y-1.5" data-testid="processes-list">
          {PROCESSES.map((p) => {
            const isActive = p.slug === active;
            const soon = p.status === "soon";
            return (
              <button
                key={p.slug}
                type="button"
                disabled={soon}
                onClick={() => !soon && setActive(p.slug)}
                data-testid={`process-tab-${p.slug}`}
                className={
                  "w-full text-left px-3 py-2.5 rounded-lg border text-sm flex items-center justify-between gap-2 transition-colors " +
                  (isActive
                    ? "bg-[var(--ayci-teal)] text-white border-transparent font-semibold"
                    : soon
                      ? "bg-white border-[var(--ayci-border)] text-[var(--ayci-ink-muted)] opacity-60 cursor-default"
                      : "bg-white border-[var(--ayci-border)] text-[var(--ayci-ink)] hover:bg-slate-50")
                }
              >
                <span>{p.title}</span>
                {soon ? (
                  <span className="text-[9px] uppercase tracking-wider inline-flex items-center gap-1">
                    <Clock className="w-3 h-3" /> soon
                  </span>
                ) : isActive ? (
                  <CheckCircle2 className="w-4 h-4" />
                ) : null}
              </button>
            );
          })}
        </nav>

        {/* Process content */}
        <div className="min-w-0 space-y-6">
          <article className="bg-white border border-[var(--ayci-border)] rounded-xl p-5 sm:p-7 prose-process">
            {Body ? <Body /> : <p className="text-[var(--ayci-ink-muted)]">Coming soon.</p>}
          </article>

          <ProcessesChat />
        </div>
      </div>
    </div>
  );
}

// "Ask about the processes" - grounded Q&A over the process docs (Claude).
function ProcessesChat() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState([]);

  const ask = async (e) => {
    e?.preventDefault?.();
    const question = q.trim();
    if (!question || busy) return;
    setQ("");
    setBusy(true);
    setLog((l) => [...l, { q: question, a: null }]);
    try {
      const { data } = await apiClient.post("/processes/ask", { question }, { timeout: 45000 });
      setLog((l) => l.map((row, i) => (i === l.length - 1 ? { ...row, a: data.answer } : row)));
    } catch (err) {
      const msg = formatApiErrorDetail(err.response?.data?.detail) || "Couldn't get an answer - try again.";
      setLog((l) => l.map((row, i) => (i === l.length - 1 ? { ...row, a: msg, error: true } : row)));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-white border border-[var(--ayci-border)] rounded-xl p-5" data-testid="processes-ask">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-9 h-9 rounded-lg bg-violet-50 border border-violet-200 flex items-center justify-center text-violet-700 shrink-0">
          <MessageCircle className="w-5 h-5" />
        </div>
        <div>
          <div className="font-display font-bold text-[var(--ayci-ink)]">Ask about the processes</div>
          <p className="text-xs text-[var(--ayci-ink-muted)]">Answers come only from the documented processes.</p>
        </div>
      </div>

      {log.length > 0 && (
        <div className="space-y-3 mb-3 max-h-96 overflow-y-auto">
          {log.map((row, i) => (
            <div key={i}>
              <div className="text-sm font-semibold text-[var(--ayci-ink)]">{row.q}</div>
              <div className={`text-sm mt-1 whitespace-pre-wrap ${row.error ? "text-rose-600" : "text-[var(--ayci-ink-muted)]"}`}>
                {row.a == null
                  ? <span className="inline-flex items-center gap-1"><Loader2 className="w-3.5 h-3.5 animate-spin" /> thinking…</span>
                  : row.a}
              </div>
            </div>
          ))}
        </div>
      )}

      <form onSubmit={ask} className="flex items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="e.g. How does a student become eligible for a bonus call?"
          className="flex-1 border border-[var(--ayci-border)] rounded-lg px-3 py-2 text-sm"
          data-testid="processes-ask-input"
        />
        <button
          type="submit"
          disabled={busy || !q.trim()}
          className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-[var(--ayci-teal)] text-white text-sm font-semibold disabled:opacity-50"
          data-testid="processes-ask-send"
        >
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          Ask
        </button>
      </form>
    </div>
  );
}

// ----------------------------------------------------------------- content
function H({ children }) {
  return <h2 className="font-display font-bold text-xl text-[var(--ayci-ink)] mt-6 mb-2 first:mt-0">{children}</h2>;
}
function P({ children }) {
  return <p className="text-sm text-[var(--ayci-ink)] leading-relaxed mb-3">{children}</p>;
}
function LI({ children }) {
  return <li className="text-sm text-[var(--ayci-ink)] leading-relaxed">{children}</li>;
}
function Tag({ children }) {
  return <code className="text-[12px] bg-slate-100 text-[var(--ayci-ink)] px-1.5 py-0.5 rounded">{children}</code>;
}
// Renders a screenshot from /public/process-img. Hides itself gracefully until
// the PNG is committed, so the doc never shows a broken image.
function Figure({ src, alt, caption }) {
  return (
    <figure className="my-4 border border-[var(--ayci-border)] rounded-lg overflow-hidden max-w-2xl">
      <img
        src={src}
        alt={alt}
        loading="lazy"
        onError={(e) => { e.currentTarget.parentElement.style.display = "none"; }}
        className="w-full block"
      />
      {caption && (
        <figcaption className="text-[11px] text-[var(--ayci-ink-muted)] px-3 py-1.5 bg-slate-50 border-t border-[var(--ayci-border)]">
          {caption}
        </figcaption>
      )}
    </figure>
  );
}

function BonusCallsDoc() {
  return (
    <div data-testid="process-bonus-calls">
      <BonusCallSummary className="mb-5" />
      <div className="flex items-center gap-2 mb-1">
        <Gift className="w-5 h-5 text-[var(--ayci-teal)]" />
        <h1 className="font-display font-extrabold text-2xl text-[var(--ayci-ink)] m-0">Bonus calls</h1>
      </div>
      <P>
        Some students get a free 30-minute 1:1 coaching call ("bonus call") depending on when they
        signed up. It's booked through a round-robin Calendly event shared by the bonus-call coaches
        (currently <strong>Anoop &amp; Charlotte</strong>) and should be used before the next cohort
        starts.
      </P>
      <P>
        <strong>Booking link (June '26):</strong>{" "}
        <a href="https://calendly.com/d/cytf-7q4-nzy/ayci-bonus-call-june-26" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline break-all">calendly.com/d/cytf-7q4-nzy/ayci-bonus-call-june-26</a>
        {" "}<em>- a fresh round-robin event is created each cohort, so this link must be updated each launch (in the doc and in the Kit booking-link automation).</em>
      </P>
      <P>
        <strong>Walkthrough video:</strong>{" "}
        <a href="https://www.loom.com/share/00eb3199d5b14c9abcc701edc101441b" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline break-all">loom.com/share/00eb3199d5b14c9abcc701edc101441b</a>
      </P>

      <H>Who's eligible</H>
      <P>A student is eligible if they hold any of these ConvertKit tags (the cohort prefix changes each launch):</P>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI><Tag>Purchase - Live webinar</Tag> - live-webinar signups (most people)</LI>
        <LI><Tag>Legacy Video Launch Day 1 Upgrade</Tag> / <Tag>... Last Day Upgrade</Tag> - legacy upgrades</LI>
        <LI><Tag>Cart Close Signup</Tag> - cart-close-day signups</LI>
        <LI><Tag>Ad Hoc Bonus Call</Tag> - allocated by hand (Arub/Tessa)</LI>
      </ul>
      <P>
        The first four are applied automatically at purchase (by Kit/Kajabi). The last one is applied
        by the dashboard when a team member marks someone eligible.
      </P>

      <H>Where the eligibility tags are applied</H>
      <P>
        The four purchase tags are applied at purchase by <strong>Zapier zaps</strong> (Kajabi purchase →
        Kit tag) - <strong>do not delete these; the whole bonus-call flow depends on them</strong>. The
        Ad Hoc tag is applied by the dashboard, so it has no zap.
      </P>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI><Tag>Purchase - Live webinar</Tag> - applied at Kajabi purchase by{" "}
          <a href="https://zapier.com/editor/356253725/published" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline">this Zapier zap</a>.</LI>
        <LI><Tag>Legacy Video Launch Day 1 Upgrade</Tag> + <Tag>Legacy Video Launch Last Day Upgrade</Tag> - applied by the zap{" "}
          <a href="https://zapier.com/editor/365778218/published" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline">"Legacy Video Launch Upgrade Bonus Kit Tags"</a>.</LI>
        <LI><Tag>Cart Close Signup</Tag> - applied by the zap{" "}
          <a href="https://zapier.com/editor/365778815" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline">"Cart Close Bonus Call - Kit tag"</a>.</LI>
        <LI><Tag>Ad Hoc Bonus Call</Tag> - applied by the <strong>dashboard</strong> (the Mark eligible button). No zap.</LI>
      </ul>

      <H>Marking someone eligible (ad hoc)</H>
      <P>
        <strong>Arub</strong> is the person who marks ad-hoc students eligible. On the student's record -
        either <strong>Student Lookup</strong> (the "Coach view" card at the top) or
        <strong>Students DB → Edit</strong> - click <strong>"Mark eligible (ad hoc)"</strong>. It tags
        them <Tag>Ad Hoc Bonus Call</Tag> in Kit, which triggers Kit's email with the booking link.
      </P>
      <Figure src="/process-img/bonus-eligibility-record.png" alt="Bonus call line on the student record"
        caption="Student Lookup - the Coach view 'Bonus call' line + Mark eligible button" />
      <Figure src="/process-img/bonus-eligibility-edit.png" alt="Mark eligible in the Students DB edit modal"
        caption="Students DB - Edit - the Bonus call box" />

      <H>What happens when they book</H>
      <P>When a student books on the Calendly bonus-call event, the dashboard automatically:</P>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI>tags them <Tag>1:1 Call Booked</Tag> in Kit - which removes them from the booking-reminder emails;</LI>
        <LI>records the booking (coach + date) on their student record;</LI>
        <LI>posts a heads-up in <Tag>#fulfillment-team</Tag>.</LI>
      </ul>
      <P>Reschedules and cancellations are picked up automatically too (with the old → new dates).</P>
      <Figure src="/process-img/bonus-connect-calendly.png" alt="Connect Calendly card in Settings"
        caption="Settings - Integrations - Connect Calendly (switches the booking automation on)" />

      <H>Booking under a different email</H>
      <P>
        The dashboard matches a booking to a student across their primary, Circle, and "Other emails".
        If someone books under a brand-new email it's flagged "not found" in the Slack alert - link it
        to the right student, and if they turn out to have two ConvertKit subscribers, consolidate them
        in Kit so they don't get double emails.
      </P>

      <H>Each cohort</H>
      <P>
        The team still sets up the new cohort tags, their Kit email automations, and a fresh round-robin
        Calendly event each launch. The dashboard adapts on its own - it finds the current cohort's tags
        automatically and matches the Calendly event by the words "bonus call", so no dashboard change is
        needed per cohort.
      </P>

      <H>Open tasks & to-clarify</H>
      <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-4 my-2">
        <ul className="list-disc pl-5 space-y-2 text-sm text-[var(--ayci-ink)]">
          <li><strong>[Tessa / Arub - Kit]</strong> Ad-hoc booking link: the dashboard tags ad-hoc students <Tag>Ad Hoc Bonus Call</Tag>, but there's no Kit automation yet that emails them the booking link off that tag. Set one up (or add the tag as an entry point to the consolidated automation below) so ad-hoc people actually get the link.</li>
          <li><strong>[Tessa - decision]</strong> Consolidate the four booking-link Kit automations (Live Webinar / Legacy Day 1 / Legacy Last Day / Cart Close) into <em>one</em> automation with all four purchase tags <em>plus</em> the Ad Hoc tag as entry points. Cleaner: one booking link + one email to maintain each launch.</li>
          <li><strong>[Kit - fix]</strong> The four booking-link emails currently show the <em>wrong cohort name</em>. Fix before the next send (consolidating to one automation makes this a one-place fix).</li>
          <li><strong>[Megan - Kit]</strong> Booking reminders ("Bonus Call Reminders (Megan)") currently only include Live Webinar signups. Add Legacy Day 1, Legacy Last Day, Cart Close, and Ad Hoc as entry points so they get reminders too.</li>
          <li><strong>[Arub]</strong> Add the <Tag>Ad Hoc Bonus Call</Tag> tag to the list of Kit tags set up for each new cohort.</li>
          <li><strong>[Megan]</strong> Agree (a) a deadline for coaches' bonus-call availability to be set on Calendly ahead of each cohort, and (b) a frequency for checking the booking calendar's availability.</li>
        </ul>
      </div>

      <H>Setting up for a new cohort</H>
      <P>
        Each launch, the team sets up the Kit + Calendly side. The dashboard itself needs <strong>no
        changes</strong> - it finds the new cohort's tags by suffix and matches the Calendly event by the
        words "bonus call".
      </P>
      <ol className="list-decimal pl-5 space-y-1.5 mb-3">
        <LI><strong>Kit tags [Arub]:</strong> create the cohort's tags - <Tag>Purchase - Live webinar</Tag>, <Tag>Legacy Video Launch Day 1 Upgrade</Tag>, <Tag>Legacy Video Launch Last Day Upgrade</Tag>, <Tag>Cart Close Signup</Tag>, and <Tag>Ad Hoc Bonus Call</Tag>.</LI>
        <LI><strong>Booking-link automation [Tessa/Megan]:</strong> the Kit automation that emails the booking link - ideally one automation with all five tags as entry points. Update the booking link and the cohort name in the email copy.</LI>
        <LI><strong>Reminders [Megan]:</strong> ensure the "Bonus Call Reminders" sequence has all five eligibility tags as entry points (not just Live Webinar).</LI>
        <LI><strong>Calendly [Arub/Megan]:</strong> create a fresh round-robin "AYCI Bonus call - &lt;cohort&gt;" event with the coaches' availability (Onboarding Week to before the next Onboarding Week). Confirm coaches + dates with Arub. <strong>Set the event's booking window to only accept bookings until the next cohort starts</strong> (date-range / scheduling limit), so calls can't roll over.</LI>
        <LI><strong>Dashboard:</strong> nothing to change. Keep Calendly connected (Settings → Integrations). It auto-detects the new tags + event.</LI>
        <LI><strong>End of cohort:</strong> read the snapshot (eligible / booked / no-show / rescheduled) on the Cohort Dashboard, share with Tessa, then the coaches.</LI>
      </ol>
    </div>
  );
}

function PrivateTierCallsDoc() {
  return (
    <div data-testid="process-private-tier-calls">
      <PrivateCallSummary className="mb-5" />
      <div className="flex items-center gap-2 mb-1">
        <Phone className="w-5 h-5 text-[var(--ayci-teal)]" />
        <h1 className="font-display font-extrabold text-2xl text-[var(--ayci-ink)] m-0">Private Tier calls</h1>
      </div>
      <P>
        Students on the <strong>Private Plus</strong>, <strong>VIP</strong> and <strong>Boost & Go Plus</strong>{" "}
        packages get a set of free 1:1 coaching calls. They can use them <strong>any time</strong> - there
        is no expiry (people were previously told 12 months, but they can keep their allowance for as
        long as they need).
      </P>
      <P>
        <strong>Walkthrough video:</strong>{" "}
        <a href="https://www.loom.com/share/9d9aa53be0d648159fe25bbf809d268e" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline break-all">loom.com/share/9d9aa53be0d648159fe25bbf809d268e</a>
      </P>

      <H>Who gets what</H>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI><strong>Private Plus</strong> - 1 x 30-minute coach call.</LI>
        <LI><strong>VIP</strong> - 2 x 30-minute calls with Tessa, 2 x 30-minute coach calls, and 1 x 60-minute mock interview (5 calls in total).</LI>
        <LI><strong>Boost & Go Plus</strong> - 2 x 30-minute coach calls (with Becky, Anoop, or Charlotte - the same 30-min coach link as above). Plain Boost & Go gets a private chat but no calls.</LI>
      </ul>
      <P>
        <strong>Boost & Go Plus students are usually existing Academy members</strong> who upgrade. Once
        they're tagged <strong>B&G Plus</strong> on the dashboard (their record's Boost & Go field), their
        call allowance shows automatically and their private chat is created by the Boost & Go chat zap.
      </P>

      <H>Who's eligible &amp; how it's identified</H>
      <P>
        When a student buys a Private Plus or VIP package, the <strong>Sales Zap</strong> tags them in
        <strong> ConvertKit</strong> for the current cohort:
      </P>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI><Tag>[AYCI MON-YY] Cohort - Private Plus</Tag> / <Tag>... Private Plus (4-Pay)</Tag></LI>
        <LI><Tag>[AYCI MON-YY] Cohort - VIP</Tag> / <Tag>... VIP (6-Pay)</Tag> / <Tag>... VIP (12-Pay)</Tag></LI>
      </ul>
      <P>
        That tier flows through to the dashboard as the student's <strong>tier</strong>, which is what
        sets their call allowance. The <strong>Sales Zap</strong> that applies these Kit tier tags is{" "}
        <a href="https://zapier.com/editor/365773719/published" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline">here</a>.
      </P>

      <H>How they get the booking links</H>
      <P>Eligible students get the booking links in two places:</P>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI>the onboarding email they receive via the <Tag>[AYCI MON-YY] Onboarding (Megan)</Tag> Kit automation (<a href="https://app.kit.com/automations/1982218/edit" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline">here</a>); and</LI>
        <LI>an initial post from <strong>Coralie</strong> in their private chat, containing the same links.</LI>
      </ul>

      <H>The booking links &amp; coaches</H>
      <P><strong>Private Plus</strong> - the 30-minute coach call (with Becky, Charlotte, or Anoop):</P>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI><a href="https://calendly.com/d/cxkz-kf9-xb4/ayci-1-1-30-min" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline break-all">calendly.com/d/cxkz-kf9-xb4/ayci-1-1-30-min</a></LI>
      </ul>
      <P><strong>VIP</strong> - five calls across three links:</P>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI>2 x 30-min <strong>with Tessa</strong> - <a href="https://calendly.com/tessardavis/ayci-vip-30-min" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline break-all">calendly.com/tessardavis/ayci-vip-30-min</a></LI>
        <LI>2 x 30-min <strong>coach calls</strong> (with Becky, Anoop, or Charlotte) - the same <a href="https://calendly.com/d/cxkz-kf9-xb4/ayci-1-1-30-min" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline break-all">calendly.com/d/cxkz-kf9-xb4/ayci-1-1-30-min</a> link as Private Plus</LI>
        <LI>1 x 60-min <strong>mock interview</strong> (with Becky, Charlotte, or Anoop) - <a href="https://calendly.com/d/cttc-mx5-gz6/ayci-1-1-60-min" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline break-all">calendly.com/d/cttc-mx5-gz6/ayci-1-1-60-min</a></LI>
      </ul>

      <H>Keeping coaching availability open</H>
      <P>
        Unlike bonus calls, these links stay live all year, so availability has to be kept topped up:
      </P>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI>coach availability needs to be set up on Calendly <strong>each month</strong>;</LI>
        <LI>availability should run <strong>consistently throughout the year</strong>; and</LI>
        <LI>do <strong>regular checks</strong> on each booking link to confirm there's enough open: the Private Plus 30-min coach call, the VIP 60-min mock, the VIP 2 x 30-min coach calls, and the VIP 2 x 30-min Tessa calls.</LI>
      </ul>

      <H>How bookings are tracked</H>
      <P>When a student books any of these calls, the dashboard automatically:</P>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI>logs the call against their record - which call it was, the coach, and the date;</LI>
        <LI>shows their allowance used vs. remaining (e.g. a VIP who's booked 1 of their 2 Tessa calls); and</LI>
        <LI>posts a heads-up in <Tag>#fulfillment-team</Tag>.</LI>
      </ul>
      <P>
        If a student <strong>reschedules</strong>, the dashboard updates the date automatically. If a
        student <strong>doesn't show up</strong>, the coach opens that student's <strong>Student Lookup</strong>{" "}
        card and marks that call a <strong>no-show</strong>.
      </P>
      <P>
        On the Student Lookup card (or <strong>Students DB → Edit</strong>), the team can also <strong>log a
        call that wasn't booked through Calendly</strong> ("Log a call" - it counts as one of their eligible
        calls), and <strong>grant extra allowance</strong> above the tier default with the <strong>+ / -</strong>
        buttons next to a call type (e.g. give a VIP a 3rd coach call).
      </P>

      <H>Reminders to book</H>
      <P>
        <strong>Coralie</strong> keeps track of who has interviews coming up and checks in with private-tier
        students to make sure they know how to book and to remind them of their remaining allowance.
      </P>

      <H>Tracking the data</H>
      <P>
        On the <strong>1st of each month</strong> the dashboard automatically posts the previous month's
        summary to the <strong>#private-tiers</strong> Slack channel - how many 1:1 calls were held, broken
        down by <strong>tier</strong>, <strong>call type</strong> and <strong>coach</strong> (plus no-shows
        and cancellations). No one needs to compile it by hand.
      </P>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI><strong>Monthly Slack summary (#private-tiers, automatic on the 1st):</strong> 1:1 calls held, by tier, call type and coach.</LI>
        <LI>A summary of how many private-tier students had interviews, and how much of their call allowance they used.</LI>
      </ul>

      <H>Each cohort</H>
      <P>
        The dashboard needs <strong>no change</strong> per cohort - it reads the tier off each student and
        matches the Calendly events by name, so the same booking links carry over. The team's per-launch
        jobs are: confirm the Sales Zap is tagging the new cohort's tier tags, update the cohort prefix in
        the onboarding email + Coralie's private-chat post, and check coach availability is set on all
        the booking links.
      </P>
    </div>
  );
}

function PrivateChatDoc() {
  return (
    <div data-testid="process-private-chat">
      <div className="flex items-center gap-2 mb-1">
        <Users className="w-5 h-5 text-[var(--ayci-teal)]" />
        <h1 className="font-display font-extrabold text-2xl text-[var(--ayci-ink)] m-0">Private chat</h1>
      </div>
      <P>
        Every <strong>Private Plus</strong>, <strong>VIP</strong> and active <strong>Boost & Go</strong>{" "}
        student gets a <strong>private group chat on Circle</strong> with the coaching team. It's where
        they ask questions and get their video feedback, and it carries the links they need.
      </P>

      <H>Who's in the chat</H>
      <P>
        The student plus the coaches: <strong>Tessa, Arub, Coralie and Becky</strong>. (Oksana is no
        longer added to new chats - older chats keep whoever was in them, since you can't remove people
        from a Circle group DM.) The coach list is editable in{" "}
        <strong>Settings → Integrations → Private chat setup</strong>.
      </P>

      <H>How a chat gets created</H>
      <P>
        There are two paths. <strong>The Zapier zaps are the primary, reliable creator</strong> - the
        dashboard "Create chat" button is a manual fallback (it can occasionally fail on Circle's side, so
        don't rely on it as the only route yet).
      </P>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI>
          <strong>Automatically (primary)</strong> - Zapier creates the chat when the student joins the
          cohort. This is the dependable path. Separate zaps cover the audiences:
          <ul className="list-disc pl-5 space-y-1 mt-1">
            <LI>VIP &amp; Private Plus members - <a href="https://zapier.com/editor/356003238/published" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline">zap</a> (and the "In Between" join variant)</LI>
            <LI>Legacy Upgrades - <a href="https://zapier.com/editor/356048959/published" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline">zap</a></LI>
            <LI>VIP &amp; Private Plus (standard join) - <a href="https://zapier.com/editor/370426888/published" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline">zap</a></LI>
            <LI><strong>Boost &amp; Go</strong> (its own zap - 4 paths: B&amp;G / B&amp;G Plus × Presentation) - <a href="https://zapier.com/editor/341446766/published" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline">zap</a></LI>
          </ul>
        </LI>
        <LI>
          <strong>Manually (fallback)</strong> - the <strong>"Create chat"</strong> button on a student in
          <strong> Students DB</strong> (and on the "Needs setup" list), for backlog or anyone the zaps
          missed. It adds the coaches + student, posts the welcome message, records the URL, and checks
          first that no chat already exists (safe to press). It now tells you the outcome - if it fails it
          shows the reason (e.g. their Circle DMs are off, or a Circle hiccup) rather than doing nothing.
        </LI>
      </ul>

      <P>
        <em>Boost &amp; Go is a separate track:</em> B&amp;G students are tagged in Kit by their own{" "}
        <a href="https://zapier.com/editor/262763852/published" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline">Boost &amp; Go Sales zap</a> (not the Private Plus / VIP
        Sales Zap), and their chat is created by the Boost &amp; Go chat zap above - not the VIP/Private
        Plus zaps.
      </P>

      <H>The welcome message</H>
      <P>
        An initial message is posted from <strong>Coralie</strong>. Its content is set on the dashboard
        in <strong>Settings → Integrations → Private chat setup</strong> - there's a separate template per
        tier (Private Plus / VIP / Boost & Go), with placeholders like <Tag>{"{first_name}"}</Tag> and{" "}
        <Tag>{"{video_allowance}"}</Tag>, and it includes the call booking link(s) and their video-answer
        link. (If a tier has no template set, the chat won't be created - so the wrong message can't go out.)
      </P>

      <H>Where the chat is tracked</H>
      <P>
        The chat URL is stored on the student's record as their <strong>private chat link</strong> (visible
        in Student Lookup and Students DB). Some older zap-created chats never wrote their URL back; the
        dashboard can recover those by scanning Circle and recording the link automatically.
      </P>

      <H>Needs setup</H>
      <P>
        Any private-tier / Boost & Go student <strong>without</strong> a chat link shows in{" "}
        <strong>Students DB → "Needs setup"</strong>. From there:
      </P>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI>press <strong>"Create chat"</strong> to create it on the spot; or</LI>
        <LI>if a chat already exists elsewhere, paste its URL into the student's record (Edit) by hand.</LI>
      </ul>
      <P>
        A new private-tier / Boost & Go student who lands without a chat also triggers a{" "}
        <strong>Slack heads-up in #fulfillment-team for Coralie</strong>, so they're not missed.
      </P>

      <H>If their Circle DMs are switched off</H>
      <P>
        Circle won't let a group chat be created for someone who has direct messages turned off. When that
        happens the dashboard flags the student <Tag>Awaiting DMs</Tag> (they stay in "Needs setup"). There's
        <strong> no automatic retry</strong> - once the student turns their DMs back on, press{" "}
        <strong>"Create chat"</strong> again and it'll go through.
      </P>

      <H>Heads-up: dual emails</H>
      <P>
        Chat creation matches the student to their Circle member by email. If their <strong>Circle email
        differs from their purchase / Kajabi email</strong>, the match can fail and the chat won't be created
        - so keep their <strong>Circle email / "Other emails"</strong> up to date on the record if a chat
        won't create for someone who's clearly on Circle.
      </P>

      <H>Each cohort</H>
      <P>
        The three zaps need to fire on the <strong>new cohort's tag</strong> each launch (and Coralie's
        welcome-message links should be checked). The dashboard side needs no change - it reads tier and
        the per-tier templates, which carry over.
      </P>
    </div>
  );
}

function BoostAndGoDoc() {
  return (
    <div data-testid="process-boost-and-go">
      <div className="flex items-center gap-2 mb-1">
        <Rocket className="w-5 h-5 text-[var(--ayci-teal)]" />
        <h1 className="font-display font-extrabold text-2xl text-[var(--ayci-ink)] m-0">Boost & Go</h1>
      </div>
      <P>
        <strong>Boost & Go</strong> is an add-on package, sold in two levels: <strong>Boost & Go</strong>{" "}
        and <strong>Boost & Go Plus</strong>. It's usually bought by people who are <strong>already
        Academy members</strong> (an upgrade), as well as new buyers. This page is the single source of
        truth for what each level gets and how the dashboard handles them.
      </P>

      <H>What each level gets</H>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI><strong>Boost & Go</strong> - a private chat + <strong>5 video answers</strong>. <strong>No 1:1 calls.</strong></LI>
        <LI><strong>Boost & Go Plus</strong> - a private chat + <strong>10 video answers</strong> + <strong>2 x 30-minute coach calls</strong>.</LI>
      </ul>
      <P>
        The private chat is covered in the <strong>Private chat</strong> process; the calls (Plus only) in
        the <strong>Private Tier calls</strong> process. Everything keys off one field on their record.
      </P>

      <H>The one field that drives everything: "Boost & Go"</H>
      <P>
        Each student's record has a <strong>Boost & Go</strong> field (Students DB / Student Lookup). When
        it's set, the dashboard treats them as a paying B&G customer and gives them the chat, video
        allowance, and (for Plus) the calls. <strong>If it's blank, they get nothing B&G.</strong>
      </P>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI><strong>Paying customer</strong> - the field contains <Tag>B&G</Tag> or <Tag>B&G Plus</Tag> (sometimes with "- Presentation"), or <Tag>Upgraded</Tag>.</LI>
        <LI><strong>NOT a customer</strong> - sales-pipeline states like <Tag>Offer Due</Tag>, <Tag>Offer Made</Tag>, <Tag>Declined</Tag>. These are leads, not buyers - the dashboard ignores them.</LI>
      </ul>

      <H>How they get tagged</H>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI>On a Kajabi purchase, the <strong>Boost & Go Sales zap</strong> (<a href="https://zapier.com/editor/262763852/published" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline">zap</a>, 4 paths: B&G / B&G Plus × Presentation) tags them in <strong>Kit</strong> and posts to Slack.</LI>
        <LI>Their <strong>Boost & Go field</strong> on the dashboard is what the dashboard reads. If it didn't get set automatically, set it by hand (Students DB → Edit).</LI>
      </ul>
      <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3 my-2">
        <P>
          <strong>⚠️ Dual-email gotcha:</strong> if someone bought Boost & Go under a <strong>different email</strong>
          than their Academy / Circle account, the automatic link can miss them (the Stripe backfill can't
          match them). When that happens, set their <strong>Boost & Go field by hand</strong> on their record -
          that's what makes them eligible.
        </P>
      </div>

      <H>What the dashboard does once they're tagged</H>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI><strong>Private chat</strong> - they appear in <strong>Students DB → "Needs setup"</strong> until their chat exists; it's created by the Boost & Go chat zap (<a href="https://zapier.com/editor/341446766/published" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline">zap</a>) or the dashboard "Create chat" button.</LI>
        <LI><strong>Video allowance</strong> - expected <strong>5</strong> (B&G) or <strong>10</strong> (B&G Plus). "Needs setup" flags it if their allowance is missing or doesn't match.</LI>
        <LI><strong>Calls (Plus only)</strong> - 2 x 30-min coach calls show on their record automatically; plain B&G shows no calls.</LI>
      </ul>

      <H>Common confusions</H>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI><strong>Plain B&G ≠ B&G Plus.</strong> Only <strong>Plus</strong> gets the 2 coach calls. Plain B&G is chat + videos only.</LI>
        <LI><strong>Their tier is usually still "Academy".</strong> B&G is a separate add-on, so don't expect "Boost & Go" in the Tier field - look at the <strong>Boost & Go field</strong>.</LI>
        <LI><strong>Pipeline states aren't customers.</strong> "Offer Due / Made / Declined" means a lead, not a buyer - no chat, videos, or calls.</LI>
        <LI><strong>It's a separate track from VIP/Private Plus.</strong> Different sales zap, different chat zap, different Kit tagging.</LI>
      </ul>

      <H>Each cohort</H>
      <P>
        The Sales zap tags B&G buyers on purchase and the chat zap creates their chats - both per launch.
        The dashboard side needs no change: it reads the Boost & Go field and applies the right video
        allowance + (for Plus) call allowance automatically. Main per-launch job: make sure new B&G buyers
        actually have their <strong>Boost & Go field set</strong> (watch the dual-email cases).
      </P>
    </div>
  );
}

function BossTestimonialsDoc() {
  return (
    <div data-testid="process-boss-testimonials">
      <BossChaseSummary className="mb-5" />
      <div className="flex items-center gap-2 mb-1">
        <Award className="w-5 h-5 text-[var(--ayci-teal)]" />
        <h1 className="font-display font-extrabold text-2xl text-[var(--ayci-ink)] m-0">Boss Badge & testimonials</h1>
      </div>
      <P>
        When a student lands their <strong>substantive job</strong> we celebrate it (the <strong>Boss
        Badge</strong>) and turn it into social proof - they <strong>share their win</strong> in the
        community and <strong>record a testimonial</strong> with Tessa. This is the end-to-end, and the
        whole point is that <strong>nothing slips through</strong>.
      </P>
      <P><strong>Owner: Coralie.</strong></P>

      <H>1. It starts when a student tells us they got the job</H>
      <P>
        Students tell us in all sorts of ways - the success form, a DM to a coach, an email, a message to
        Coralie. The tidy path is the <strong>substantive success form</strong>, but the rule that stops
        wins leaking is:
      </P>
      <div className="rounded-lg border border-[var(--ayci-teal)]/30 bg-emerald-50/50 p-3 my-2">
        <P>
          <strong>Coaches:</strong> if a student tells you they've got their substantive job,
          <strong> pass it to Coralie straight away.</strong> (Coaches don't all have dashboard access, so
          Coralie is the one person who records every win - that's how we make sure none are missed.)
        </P>
      </div>

      <H>2. Coralie records it on the dashboard</H>
      <P>
        Coralie opens the student and clicks <strong>"Mark as Boss"</strong> on their record. That's the
        single source of truth, and it cascades: the <strong>Boss Badge</strong> tag on Circle, the Kit
        tag + bonus-content access, and it starts the testimonial chase. <em>(The success form triggers the
        same thing automatically; a manual Circle tag is a fallback.)</em>
      </P>

      <H>3. The journey the board tracks</H>
      <P>For every Boss, the dashboard shows where they are:</P>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI><strong>Boss tagged</strong> - set when Coralie marks them (or the form fires).</LI>
        <LI><strong>Win shared</strong> - detected automatically from a post in the <a href="https://ayci-academy.circle.so/c/share-your-wins/" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline">Share Your Wins</a> space.</LI>
        <LI><strong>Testimonial booked</strong> - detected from the <strong>Testimonial Call</strong> Calendly event (<a href="https://calendly.com/tessardavis/testimonial" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline break-all">calendly.com/tessardavis/testimonial</a>).</LI>
        <LI><strong>Testimonial recorded</strong> - when the booked call actually happens.</LI>
      </ul>

      <H>4. The nudges (already automated)</H>
      <P>
        Once they're a Boss, a Circle DM sequence chases them to book the testimonial call: a first
        message from Coralie, then three follow-ups, each carrying the booking link. They stop
        automatically once the call is booked.
      </P>

      <H>5. Coralie's "Bosses to chase" view</H>
      <P>
        The board surfaces who's stuck at each step - tagged but hasn't shared their win, or hasn't
        booked, or booked but not yet recorded - so Coralie can give the stragglers a personal nudge on
        top of the automated DMs.
      </P>

      <H>Key links</H>
      <ul className="list-disc pl-5 space-y-1 mb-3">
        <LI>Wins channel: <a href="https://ayci-academy.circle.so/c/share-your-wins/" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline">Share Your Wins</a></LI>
        <LI>Testimonial booking: <a href="https://calendly.com/tessardavis/testimonial" target="_blank" rel="noreferrer" className="text-[var(--ayci-teal)] underline break-all">calendly.com/tessardavis/testimonial</a></LI>
      </ul>

      <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-4 my-2">
        <ul className="list-disc pl-5 space-y-2 text-sm text-[var(--ayci-ink)]">
          <li><strong>[Tessa - Zapier]</strong> Consolidate the Boss-tagging zaps (success form + manual Circle tag + the Monday taggers) so "becoming a Boss" has one clean path.</li>
          <li><strong>[Tessa - Zapier/scorecard]</strong> Swap <strong>Oksana → Coralie</strong> on the "Student Wins Tracking - First Message" zap and the "Testimonial Calls Recorded" scorecard owner.</li>
        </ul>
      </div>
    </div>
  );
}
