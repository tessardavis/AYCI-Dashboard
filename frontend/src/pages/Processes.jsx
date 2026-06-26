import { useState, useEffect } from "react";
import { BookOpen, MessageCircle, Gift, CheckCircle2, Clock } from "lucide-react";

import { apiClient } from "@/lib/api";

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

          {/* Ask-Claude placeholder - wired up once the API key is added. */}
          <div className="bg-white border border-dashed border-[var(--ayci-border)] rounded-xl p-5 flex items-start gap-3" data-testid="processes-ask-placeholder">
            <div className="w-9 h-9 rounded-lg bg-violet-50 border border-violet-200 flex items-center justify-center text-violet-700 shrink-0">
              <MessageCircle className="w-5 h-5" />
            </div>
            <div>
              <div className="font-display font-bold text-[var(--ayci-ink)]">Ask about the processes</div>
              <p className="text-sm text-[var(--ayci-ink-muted)] mt-0.5">
                Coming soon - a chat box here will let the team ask questions and get answers
                drawn from these process docs. Switches on once the Claude API key is added.
              </p>
            </div>
          </div>
        </div>
      </div>
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

// Live "this cohort" snapshot at the top of the Bonus calls doc. Hidden for
// anyone without students-board access (the endpoint 403s -> we just don't show).
function BonusCallSummary() {
  const [data, setData] = useState(null);
  useEffect(() => {
    apiClient.get("/bonus-call/summary").then(({ data }) => setData(data)).catch(() => {});
  }, []);
  if (!data) return null;
  const s = data.by_status || {};
  const ORDER = ["Booked", "Attended", "No-show", "Rescheduled", "Cancelled", "Done", "Eligible"];
  const chips = [
    ...ORDER.filter((k) => s[k]).map((k) => [k, s[k]]),
    ...Object.entries(s).filter(([k]) => !ORDER.includes(k)),
  ];
  return (
    <div className="mb-5 rounded-lg border border-[var(--ayci-border)] bg-slate-50 p-4" data-testid="bonus-summary">
      <div className="text-[11px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)] mb-2">
        This cohort - snapshot
      </div>
      <div className="flex flex-wrap gap-2 items-center">
        {data.eligible != null && (
          <span className="text-sm mr-1">
            <strong className="text-lg text-[var(--ayci-ink)]">{data.eligible}</strong> eligible
          </span>
        )}
        {chips.map(([k, n]) => (
          <span key={k} className="text-xs px-2 py-1 rounded-full bg-white border border-[var(--ayci-border)]">
            {k}: <strong>{n}</strong>
          </span>
        ))}
        {data.tracked === 0 && (
          <span className="text-xs text-[var(--ayci-ink-muted)]">No bookings recorded yet this cohort.</span>
        )}
      </div>
    </div>
  );
}

function BonusCallsDoc() {
  return (
    <div data-testid="process-bonus-calls">
      <BonusCallSummary />
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
    </div>
  );
}
