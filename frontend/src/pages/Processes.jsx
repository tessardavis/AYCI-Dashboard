import { useState } from "react";
import { BookOpen, MessageCircle, Gift, CheckCircle2, Clock, Loader2, Send } from "lucide-react";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import BonusCallSummary from "@/components/BonusCallSummary";

// In-dashboard process docs the whole team can read. Add a process by adding an
// entry here. The canonical/source copy also lives in PROCESSES.md in the repo.
const PROCESSES = [
  { slug: "bonus-calls", title: "Bonus calls", status: "ready", body: BonusCallsDoc },
  { slug: "one-to-one-calls", title: "1:1 call allowances", status: "soon" },
  { slug: "mock-interviews", title: "Mock interview allowances", status: "soon" },
  { slug: "testimonials", title: "Testimonial status", status: "soon" },
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

      <H>Marking someone eligible (ad hoc)</H>
      <P>
        On a student's record - either <strong>Student Lookup</strong> (the "Coach view" card at the top)
        or <strong>Students DB → Edit</strong> - use the <strong>"Mark eligible (ad hoc)"</strong> button.
        It tags them <Tag>Ad Hoc Bonus Call</Tag> in Kit, which triggers Kit's email with the booking link.
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
        <LI><strong>Calendly [Arub/Megan]:</strong> create a fresh round-robin "AYCI Bonus call - &lt;cohort&gt;" event with the coaches' availability (Onboarding Week to before the next Onboarding Week). Confirm coaches + dates with Arub.</LI>
        <LI><strong>Dashboard:</strong> nothing to change. Keep Calendly connected (Settings → Integrations). It auto-detects the new tags + event.</LI>
        <LI><strong>End of cohort:</strong> read the snapshot (eligible / booked / no-show / rescheduled) on the Cohort Dashboard, share with Tessa, then the coaches.</LI>
      </ol>
    </div>
  );
}
