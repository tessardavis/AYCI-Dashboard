import { useEffect, useState } from "react";
import { Briefcase, Calendar, Loader2, ExternalLink, MessageSquare, Video, Phone, Target, History, Users2, AlertTriangle, AlertOctagon, CheckCircle2, Clock } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";

const fmtDate = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
};

const daysUntil = (iso, todayIso) => {
  const d = new Date(iso + "T00:00:00Z");
  const today = new Date(todayIso + "T00:00:00Z");
  const diff = Math.round((d - today) / (1000 * 60 * 60 * 24));
  if (diff === 0) return "today";
  if (diff === 1) return "tomorrow";
  return `in ${diff} days`;
};


// ---------------------------------------------------------------- EveScoreChip
// Surfaces the student's "How supported do you feel?" pre-interview check-in
// score (sent the evening before via Coralie's account). Three states:
//   • DM not yet sent (e.g. interview is still >24h away) → null (hidden)
//   • DM sent, no score yet → grey pill "Eve · pending"
//   • Score received → coloured pill "N/10" (red ≤5, amber 6-7, green 8-10)
function EveScoreChip({ eve }) {
  if (!eve) return null;
  const score = eve.score;
  if (score == null) {
    return (
      <span
        className="inline-flex items-center gap-1 px-2 py-0.5 bg-slate-100 text-slate-600 border border-slate-200 rounded-full text-[10px] uppercase tracking-wider font-bold"
        title={`Eve-of-interview check-in DM sent ${new Date(eve.sent_at).toLocaleString("en-GB")} — no score reply yet`}
        data-testid="eve-score-pending"
      >
        💬 Eve · pending
      </span>
    );
  }
  const tone =
    score <= 5
      ? "bg-rose-100 text-rose-900 border-rose-300"
      : score <= 7
        ? "bg-amber-100 text-amber-900 border-amber-300"
        : "bg-emerald-100 text-emerald-900 border-emerald-300";
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 ${tone} border rounded-full text-[10px] uppercase tracking-wider font-bold`}
      title={`Pre-interview support score ${score}/10 — replied ${new Date(eve.score_received_at).toLocaleString("en-GB")}`}
      data-testid={`eve-score-${score}`}
    >
      {score <= 5 ? "🚨" : score <= 7 ? "🟡" : "✅"} Eve {score}/10
    </span>
  );
}


function InterviewTypeBadge({ type }) {
  const isLocum = (type || "").toLowerCase().includes("locum");
  const cls = isLocum
    ? "bg-amber-50 text-amber-700 border-amber-200"
    : "bg-sky-50 text-sky-700 border-sky-200";
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 border rounded-full text-[10px] uppercase tracking-wider font-semibold ${cls}`}
      data-testid="interview-type-badge"
    >
      <Briefcase className="w-3 h-3" />
      {type}
    </span>
  );
}

function HistoryBadge({ count }) {
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 bg-slate-100 text-slate-700 border border-slate-200 rounded-full text-[10px] uppercase tracking-wider font-semibold"
      title="Previous Tally interview submissions for this student"
      data-testid="tally-history-badge"
    >
      <History className="w-3 h-3" />
      {count} prior{count > 1 ? " interviews" : ""}
    </span>
  );
}

// Strips trailing email-like fragments from Calendly host names so we get
// "Tessa Davis" instead of "Tessa Davis (tessa@…)".
function cleanCoachName(name) {
  if (!name) return "Unknown";
  return String(name).replace(/\s*\(.*?\)\s*$/, "").trim() || name;
}

function PastCoaches({ coaches }) {
  if (!coaches || coaches.length === 0) return null;
  // Show top 3 by recency, summarise the rest
  const top = coaches.slice(0, 3);
  const extra = coaches.length - top.length;
  const fmtSessionDate = (iso) => {
    if (!iso) return null;
    try {
      return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
    } catch {
      return null;
    }
  };
  return (
    <div
      className="mt-2 flex items-center gap-1.5 flex-wrap text-[11px] text-[var(--ayci-ink-muted)]"
      data-testid="past-coaches"
    >
      <Users2 className="w-3 h-3 text-[var(--ayci-teal)]" />
      <span className="uppercase tracking-wider font-semibold text-[10px]">
        Spoke with
      </span>
      {top.map((c) => {
        const dates = (c.dates || [])
          .map(fmtSessionDate)
          .filter(Boolean);
        // De-dup while preserving most-recent-first ordering
        const uniqueDates = Array.from(new Set(dates));
        const timelineTitle = uniqueDates.length
          ? `Past sessions:\n• ${uniqueDates.join("\n• ")}`
          : null;
        return (
          <span
            key={c.name}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-sky-50 border border-sky-200 text-sky-700 rounded-full font-medium"
            title={`${c.count} call${c.count > 1 ? "s" : ""}${c.last_at ? ` — last ${new Date(c.last_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}` : ""}`}
            data-testid={`past-coach-chip-${cleanCoachName(c.name).replace(/\s+/g, "-").toLowerCase()}`}
          >
            {cleanCoachName(c.name)}
            {c.count > 1 && (
              <span className="text-[9px] opacity-70">×{c.count}</span>
            )}
            {timelineTitle && (
              <Clock
                className="w-3 h-3 ml-0.5 text-sky-600 cursor-help opacity-80 hover:opacity-100"
                title={timelineTitle}
                data-testid="past-coach-timeline-icon"
              />
            )}
          </span>
        );
      })}
      {extra > 0 && (
        <span className="text-[10px] opacity-70">+{extra} more</span>
      )}
    </div>
  );
}

export default function UpcomingInterviews() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState("private"); // "private" | "all"
  const [academyDays, setAcademyDays] = useState(7);
  const [privateDays, setPrivateDays] = useState(14);
  const [utilisation, setUtilisation] = useState(null);
  const [utilLoading, setUtilLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get(`/interviews/upcoming`, {
        params: { academy_days: academyDays, private_days: privateDays },
        timeout: 45000,
      });
      setData(data);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load upcoming interviews");
    } finally {
      setLoading(false);
    }
  };

  const loadUtilisation = async () => {
    setUtilLoading(true);
    try {
      const { data } = await apiClient.get(`/interviews/private-tier-utilisation`, {
        params: { days: privateDays },
        timeout: 60000,
      });
      setUtilisation(data);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load tier utilisation");
    } finally {
      setUtilLoading(false);
    }
  };

  useEffect(() => {
    load();
    loadUtilisation();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [academyDays, privateDays]);

  const showAcademy = view === "all";

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="upcoming-interviews-page">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="text-[11px] font-display font-semibold tracking-[0.25em] uppercase text-[var(--ayci-teal)]">
            Who's up
          </div>
          <h1 className="text-4xl font-display font-bold text-[var(--ayci-ink)] mt-1">
            Upcoming Interviews
          </h1>
          <p className="text-[var(--ayci-ink-muted)] text-sm mt-1 max-w-2xl">
            Pulled live from the Monday Academy Members board.
            {showAcademy ? (
              <>
                {" "}Academy students shown for the next {academyDays} days; private tier + Boost & Go shown for the next {privateDays} days with their call / video allowance usage.
              </>
            ) : (
              <>
                {" "}Showing private tier + Boost & Go for the next {privateDays} days with call / video allowance usage. Switch to "All tiers" to also see Academy students.
              </>
            )}
          </p>
        </div>
        <div className="flex gap-2 items-center flex-wrap">
          <div className="flex bg-white border border-[var(--ayci-border)] rounded-lg p-1" data-testid="view-toggle">
            <button
              onClick={() => setView("private")}
              className={
                "px-3 py-1.5 text-sm rounded-md font-medium transition-colors " +
                (view === "private"
                  ? "bg-[var(--ayci-teal)] text-white"
                  : "text-[var(--ayci-ink-muted)] hover:bg-slate-50")
              }
              data-testid="view-private-only"
            >
              Private only
            </button>
            <button
              onClick={() => setView("all")}
              className={
                "px-3 py-1.5 text-sm rounded-md font-medium transition-colors " +
                (view === "all"
                  ? "bg-[var(--ayci-teal)] text-white"
                  : "text-[var(--ayci-ink-muted)] hover:bg-slate-50")
              }
              data-testid="view-all-tiers"
            >
              All tiers
            </button>
          </div>
          {showAcademy && (
            <Selector
              label="Academy window"
              value={academyDays}
              onChange={setAcademyDays}
              options={[7, 14]}
              testid="academy-window-selector"
            />
          )}
          <Selector
            label="Private window"
            value={privateDays}
            onChange={setPrivateDays}
            options={[7, 14, 30]}
            testid="private-window-selector"
          />
        </div>
      </div>

      {loading && !data && (
        <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-8 text-center text-[var(--ayci-ink-muted)]">
          <Loader2 className="w-6 h-6 animate-spin mx-auto mb-3 text-[var(--ayci-teal)]" />
          Loading upcoming interviews from Monday…
        </div>
      )}

      <UtilisationSection
        utilisation={utilisation}
        loading={utilLoading}
        days={privateDays}
      />

      {data && (
        <div className={"grid grid-cols-1 gap-6 " + (showAcademy ? "xl:grid-cols-2" : "")}>
          {/* Private — always shown */}
          <section data-testid="private-section">
            <SectionHeader
              title="Private tier · Boost & Go"
              count={data.private.length}
              subtitle={`Next ${privateDays} days · until ${fmtDate(data.private_window.end)}`}
              accent="bg-violet-100 text-violet-700"
            />
            {data.private.length === 0 ? (
              <EmptyState text={`No private-tier interviews in the next ${privateDays} days.`} />
            ) : (
              <ul className="space-y-3">
                {data.private.map((s) => (
                  <PrivateCard key={s.id} student={s} today={data.today} />
                ))}
              </ul>
            )}
          </section>

          {/* Academy — only when 'All tiers' is selected */}
          {showAcademy && (
            <section data-testid="academy-section">
              <SectionHeader
                title="Academy students"
                count={data.academy.length}
                subtitle={`Next ${academyDays} days · until ${fmtDate(data.academy_window.end)}`}
                accent="bg-sky-100 text-sky-700"
              />
              {data.academy.length === 0 ? (
                <EmptyState text={`No Academy interviews in the next ${academyDays} days.`} />
              ) : (
                <ul className="space-y-2">
                  {data.academy.map((s) => (
                    <AcademyRow key={s.id} student={s} today={data.today} />
                  ))}
                </ul>
              )}
            </section>
          )}
        </div>
      )}
    </div>
  );
}

function Selector({ label, value, onChange, options, testid }) {
  return (
    <div className="flex items-center gap-2 bg-white border border-[var(--ayci-border)] rounded-lg px-3 py-1.5">
      <span className="text-[11px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="text-sm bg-transparent border-none focus:outline-none font-medium text-[var(--ayci-ink)]"
        data-testid={testid}
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o} days
          </option>
        ))}
      </select>
    </div>
  );
}

function SectionHeader({ title, count, subtitle, accent }) {
  return (
    <div className="flex items-end justify-between mb-3">
      <div>
        <div className="flex items-center gap-2">
          <h2 className="font-display font-bold text-xl text-[var(--ayci-ink)]">{title}</h2>
          <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${accent}`}>{count}</span>
        </div>
        <div className="text-xs text-[var(--ayci-ink-muted)] mt-0.5">{subtitle}</div>
      </div>
    </div>
  );
}

function EmptyState({ text }) {
  return (
    <div className="bg-white border border-dashed border-[var(--ayci-border)] rounded-lg p-6 text-center text-[var(--ayci-ink-muted)] text-sm">
      {text}
    </div>
  );
}

function AcademyRow({ student, today }) {
  return (
    <li
      className="bg-white border border-[var(--ayci-border)] rounded-lg px-4 py-3 flex items-center justify-between gap-3 hover:shadow-sm transition-shadow"
      data-testid={`academy-row-${student.id}`}
    >
      <div className="flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <a
            href={student.monday_url}
            target="_blank"
            rel="noreferrer"
            className="font-semibold text-[var(--ayci-ink)] hover:text-[var(--ayci-teal)]"
          >
            {student.name}
          </a>
          {student.interview_type && (
            <InterviewTypeBadge type={student.interview_type} />
          )}
          {student.tally_history_count > 0 && (
            <HistoryBadge count={student.tally_history_count} />
          )}
          {student.over_allowance && (
            <span
              className="inline-flex items-center gap-1 px-2 py-0.5 bg-rose-100 text-rose-900 border border-rose-200 rounded-full text-[10px] uppercase tracking-wider font-bold"
              title={`Booked ${student.over_allowance.calendly_calls_used} Calendly calls vs Monday allowance of ${student.over_allowance.monday_total_allowance}. Oksana has been DM'd in Slack.`}
              data-testid={`over-allowance-chip-${student.email}`}
            >
              <AlertOctagon className="w-3 h-3" />
              +{student.over_allowance.over_by} over
            </span>
          )}
          <EveScoreChip eve={student.eve_score} />
        </div>
        <div className="text-xs text-[var(--ayci-ink-muted)] mt-0.5 flex flex-wrap gap-x-3">
          <span>{student.speciality || "—"}</span>
          {student.hospital && <span>· {student.hospital}</span>}
        </div>
        <PastCoaches coaches={student.past_coaches} />
      </div>
      <div className="text-right">
        <div className="text-sm font-semibold text-[var(--ayci-ink)]">{fmtDate(student.interview_date)}</div>
        <div className="text-xs text-[var(--ayci-teal)]">{daysUntil(student.interview_date, today)}</div>
      </div>
    </li>
  );
}

function PrivateCard({ student, today }) {
  const { calls_30min: calls, mock_interviews: mocks, bonus_calls: bonus, videos } = student;
  return (
    <li
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-4 shadow-sm"
      data-testid={`private-card-${student.id}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <a
              href={student.monday_url}
              target="_blank"
              rel="noreferrer"
              className="font-display font-semibold text-base text-[var(--ayci-ink)] hover:text-[var(--ayci-teal)]"
            >
              {student.name}
            </a>
            <span
              className="px-2 py-0.5 bg-violet-50 text-violet-700 border border-violet-200 rounded-full text-[10px] uppercase tracking-wider font-semibold"
              title={student.tier && student.tier !== student.tier_group ? `Sub-tier: ${student.tier}` : undefined}
            >
              {student.tier_group || student.tier}
            </span>
            {student.tier && student.tier_group && student.tier !== student.tier_group && (
              <span className="text-[10px] text-[var(--ayci-ink-muted)] tracking-wider">
                · {student.tier}
              </span>
            )}
            {student.interview_type && (
              <InterviewTypeBadge type={student.interview_type} />
            )}
            {student.tally_history_count > 0 && (
              <HistoryBadge count={student.tally_history_count} />
            )}
            {student.over_allowance && (
              <span
                className="inline-flex items-center gap-1 px-2 py-0.5 bg-rose-100 text-rose-900 border border-rose-200 rounded-full text-[10px] uppercase tracking-wider font-bold"
                title={`Booked ${student.over_allowance.calendly_calls_used} Calendly calls vs Monday allowance of ${student.over_allowance.monday_total_allowance}. Oksana has been DM'd in Slack.`}
                data-testid={`over-allowance-chip-${student.email}`}
              >
                <AlertOctagon className="w-3 h-3" />
                +{student.over_allowance.over_by} over allowance
              </span>
            )}
            <EveScoreChip eve={student.eve_score} />
          </div>
          <div className="text-xs text-[var(--ayci-ink-muted)] mt-0.5">
            {student.speciality || "—"}
            {student.hospital && ` · ${student.hospital}`}
          </div>
          <PastCoaches coaches={student.past_coaches} />
        </div>
        <div className="text-right">
          <div className="text-sm font-semibold text-[var(--ayci-ink)]">{fmtDate(student.interview_date)}</div>
          <div className="text-xs text-[var(--ayci-teal)]">{daysUntil(student.interview_date, today)}</div>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-4">
        <AllowanceStat icon={Phone} label="30-min calls" data={calls} tone="teal" />
        <AllowanceStat icon={Target} label="Mock interviews" data={mocks} tone="rose" />
        <AllowanceStat icon={Phone} label="Bonus" data={bonus} tone="amber" />
        <VideoStat videos={videos} />
      </div>

      {calls.items.length + mocks.items.length + bonus.items.length > 0 && (
        <details className="mt-3">
          <summary className="text-xs text-[var(--ayci-ink-muted)] cursor-pointer hover:text-[var(--ayci-teal)]">
            Show slot-by-slot status
          </summary>
          <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-1.5">
            {[...calls.items, ...mocks.items, ...bonus.items].map((s) => (
              <SlotRow key={s.label} slot={s} />
            ))}
          </div>
        </details>
      )}

      {student.private_chat_link && (
        <a
          href={student.private_chat_link}
          target="_blank"
          rel="noreferrer"
          className="mt-3 inline-flex items-center gap-1.5 text-xs text-[var(--ayci-teal)] hover:underline"
        >
          <MessageSquare className="w-3 h-3" />
          Private chat <ExternalLink className="w-3 h-3" />
        </a>
      )}
    </li>
  );
}

function AllowanceStat({ icon: Icon, label, data, tone }) {
  const toneMap = {
    teal: "bg-sky-50 border-sky-200 text-sky-700",
    rose: "bg-rose-50 border-rose-200 text-rose-700",
    amber: "bg-amber-50 border-amber-200 text-amber-700",
  };
  const pct = data.total ? (data.used / data.total) * 100 : 0;
  return (
    <div className={`rounded-lg border p-2.5 ${toneMap[tone] || toneMap.teal}`}>
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-semibold opacity-80">
        <Icon className="w-3 h-3" />
        {label}
      </div>
      <div className="text-[var(--ayci-ink)] mt-1 font-display font-bold text-base">
        {data.used}
        <span className="text-xs font-normal text-[var(--ayci-ink-muted)]"> / {data.total}</span>
      </div>
      {data.total > 0 && (
        <div className="mt-1.5 h-1.5 bg-white/60 rounded-full overflow-hidden">
          <div
            className="h-full bg-current opacity-70 rounded-full transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
      {data.total === 0 && <div className="text-[10px] mt-1 opacity-60">Not in tier</div>}
    </div>
  );
}

function VideoStat({ videos }) {
  const pct = videos.allowance ? (videos.submitted / videos.allowance) * 100 : 0;
  return (
    <div className="rounded-lg border bg-emerald-50 border-emerald-200 text-emerald-700 p-2.5">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-semibold opacity-80">
        <Video className="w-3 h-3" />
        Videos
      </div>
      <div className="text-[var(--ayci-ink)] mt-1 font-display font-bold text-base">
        {videos.submitted}
        <span className="text-xs font-normal text-[var(--ayci-ink-muted)]"> / {videos.allowance}</span>
      </div>
      {videos.allowance > 0 && (
        <div className="mt-1.5 h-1.5 bg-white/60 rounded-full overflow-hidden">
          <div
            className="h-full bg-current opacity-70 rounded-full"
            style={{ width: `${Math.min(100, pct)}%` }}
          />
        </div>
      )}
      {videos.allowance === 0 && <div className="text-[10px] mt-1 opacity-60">Not in tier</div>}
    </div>
  );
}

function SlotRow({ slot }) {
  const color =
    slot.status === "used"
      ? "bg-slate-100 text-slate-600"
      : slot.status === "available"
      ? "bg-emerald-50 text-emerald-700"
      : "bg-amber-50 text-amber-700";
  return (
    <div className="flex items-center justify-between text-xs bg-slate-50 rounded px-2 py-1 border border-[var(--ayci-border)]">
      <span className="font-medium text-[var(--ayci-ink)]">{slot.label}</span>
      <span className={`px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider ${color}`}>
        {slot.text}
      </span>
    </div>
  );
}

// ============================================================================
// Private Tier Utilisation — flagged students who haven't used their videos /
// calls yet, surfaced ahead of their interview so coaches can chase.
// ============================================================================
function UtilisationSection({ utilisation, loading, days }) {
  if (loading && !utilisation) {
    return (
      <div
        className="bg-white border border-[var(--ayci-border)] rounded-lg p-6 text-center text-[var(--ayci-ink-muted)]"
        data-testid="tier-utilisation-loading"
      >
        <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2 text-[var(--ayci-teal)]" />
        Loading tier utilisation…
      </div>
    );
  }
  if (!utilisation) return null;

  const ppSummary = utilisation.summary_by_tier?.["Private Plus"] || { total: 0, on_track: 0, flagged: 0 };
  const vipSummary = utilisation.summary_by_tier?.VIP || { total: 0, on_track: 0, flagged: 0 };
  const flagged = utilisation.flagged || [];
  const onTrack = utilisation.on_track || [];
  const totalStudents = ppSummary.total + vipSummary.total;

  if (totalStudents === 0) return null;

  return (
    <section
      className="bg-white border border-[var(--ayci-border)] rounded-xl shadow-sm overflow-hidden"
      data-testid="tier-utilisation-section"
    >
      {/* Header */}
      <div className="px-5 py-4 border-b border-[var(--ayci-border)] bg-gradient-to-r from-violet-50 to-pink-50">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-violet-600" />
              <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
                Private Tier Utilisation
              </h2>
              <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 bg-white/70 border border-violet-200 text-violet-700 rounded-full font-semibold">
                Next {days} days
              </span>
            </div>
            <div className="text-xs text-[var(--ayci-ink-muted)] mt-1">
              Private Plus + VIP students with an upcoming interview who haven't used enough of their video / call allowance yet.
            </div>
          </div>
          <div className="flex gap-2 flex-wrap">
            <SummaryPill
              label="Private Plus"
              total={ppSummary.total}
              flagged={ppSummary.flagged}
              onTrack={ppSummary.on_track}
            />
            <SummaryPill
              label="VIP"
              total={vipSummary.total}
              flagged={vipSummary.flagged}
              onTrack={vipSummary.on_track}
            />
          </div>
        </div>
      </div>

      {/* Flagged table */}
      {flagged.length > 0 ? (
        <div className="overflow-x-auto" data-testid="flagged-table-wrapper">
          <table className="w-full text-sm" data-testid="flagged-table">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] bg-slate-50">
                <th className="px-4 py-2 font-semibold">Student</th>
                <th className="px-3 py-2 font-semibold">Tier</th>
                <th className="px-3 py-2 font-semibold">Interview</th>
                <th className="px-3 py-2 font-semibold text-center">Videos</th>
                <th className="px-3 py-2 font-semibold text-center">Calls</th>
                <th className="px-3 py-2 font-semibold">Action needed</th>
              </tr>
            </thead>
            <tbody>
              {flagged.map((s) => (
                <FlaggedRow key={s.monday_id} student={s} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="px-5 py-6 text-center text-sm text-[var(--ayci-ink-muted)] bg-emerald-50/30">
          <CheckCircle2 className="w-5 h-5 text-emerald-600 mx-auto mb-1" />
          All Private Plus + VIP students with an interview in the next {days} days are on track.
        </div>
      )}

      {/* On-track collapsed list (default open so coaches see everyone with
          an interview this week, not just the flagged ones) */}
      {onTrack.length > 0 && (
        <details className="border-t border-[var(--ayci-border)]" data-testid="on-track-details" open>
          <summary className="px-5 py-2.5 text-xs uppercase tracking-wider text-[var(--ayci-ink-muted)] cursor-pointer hover:bg-slate-50 flex items-center gap-2">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
            On track ({onTrack.length})
          </summary>
          <div className="overflow-x-auto bg-slate-50/40">
            <table className="w-full text-sm">
              <tbody>
                {onTrack.map((s) => (
                  <FlaggedRow key={s.monday_id} student={s} okay />
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  );
}

function SummaryPill({ label, total, flagged, onTrack }) {
  if (total === 0) return null;
  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-lg px-3 py-1.5 flex items-center gap-2"
      data-testid={`tier-summary-${label.toLowerCase().replace(/\s+/g, "-")}`}
    >
      <span className="text-[11px] uppercase tracking-wider font-semibold text-[var(--ayci-ink-muted)]">
        {label}
      </span>
      <span className="text-sm font-display font-bold text-[var(--ayci-ink)]">{total}</span>
      <span className="text-[11px] text-rose-600 font-semibold">{flagged} flagged</span>
      <span className="text-[11px] text-emerald-600 font-semibold">{onTrack} ok</span>
    </div>
  );
}

function FlaggedRow({ student, okay = false }) {
  const tierColor = student.tier === "VIP"
    ? "bg-amber-50 text-amber-700 border-amber-200"
    : "bg-violet-50 text-violet-700 border-violet-200";
  const daysColor = student.days_until <= 3
    ? "text-rose-600 font-bold"
    : student.days_until <= 7
    ? "text-amber-700 font-semibold"
    : "text-[var(--ayci-ink)] font-semibold";
  const videosOk = student.videos_submitted >= student.videos_min;
  const callsOk = student.calls_used >= student.calls_min;
  return (
    <tr
      className="border-t border-[var(--ayci-border)] hover:bg-slate-50/50"
      data-testid={`flagged-row-${student.monday_id}`}
    >
      <td className="px-4 py-2.5">
        <a
          href={student.monday_url}
          target="_blank"
          rel="noreferrer"
          className="font-semibold text-[var(--ayci-ink)] hover:text-[var(--ayci-teal)]"
        >
          {student.name}
        </a>
        <div className="text-[11px] text-[var(--ayci-ink-muted)] flex items-center gap-1.5 flex-wrap">
          {student.interview_type && (
            <span
              className={
                "uppercase tracking-wider font-semibold text-[9px] px-1.5 py-0.5 rounded " +
                (student.interview_type.toLowerCase() === "locum"
                  ? "bg-amber-50 text-amber-700 border border-amber-200"
                  : "bg-slate-100 text-slate-700 border border-slate-200")
              }
            >
              {student.interview_type}
            </span>
          )}
          {student.speciality && <span>{student.speciality}</span>}
        </div>
      </td>
      <td className="px-3 py-2.5">
        <span className={`text-[10px] uppercase tracking-wider px-1.5 py-0.5 border rounded-full font-semibold ${tierColor}`}>
          {student.tier}
        </span>
      </td>
      <td className="px-3 py-2.5">
        <div className={daysColor + " text-sm"}>
          {student.days_until === 0 ? "Today"
            : student.days_until === 1 ? "Tomorrow"
            : `In ${student.days_until} d`}
        </div>
        <div className="text-[11px] text-[var(--ayci-ink-muted)]">
          {new Date(student.interview_date + "T00:00:00Z").toLocaleDateString("en-GB", {
            day: "numeric", month: "short", timeZone: "UTC",
          })}
        </div>
      </td>
      <td className="px-3 py-2.5 text-center">
        <span className={(okay || videosOk ? "text-emerald-700" : "text-rose-600") + " font-semibold"}>
          {student.videos_submitted}
        </span>
        <span className="text-[var(--ayci-ink-muted)] text-xs"> / {student.videos_allowance}</span>
      </td>
      <td className="px-3 py-2.5 text-center">
        <span className={(okay || callsOk ? "text-emerald-700" : "text-rose-600") + " font-semibold"}>
          {student.calls_used}
        </span>
        <span className="text-[var(--ayci-ink-muted)] text-xs"> / {student.calls_allowance}</span>
      </td>
      <td className="px-3 py-2.5 text-xs text-[var(--ayci-ink-muted)]">
        {okay ? (
          <span className="text-emerald-700 font-semibold">On track</span>
        ) : (
          (student.reasons || []).join(" · ")
        )}
      </td>
    </tr>
  );
}
