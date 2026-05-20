import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Briefcase, Calendar, Loader2, ExternalLink, MessageSquare, Video, Phone, Target, History, Users2, AlertTriangle, AlertOctagon, CheckCircle2, Clock, Search, HeartPulse, RefreshCcw, PhoneCall, Plus } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useDeployVersion } from "@/hooks/useDeployVersion";
import DeployBadge from "@/components/DeployBadge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";

// Module-scoped dedupe so the same email isn't re-prefetched within a
// session if the coach hovers it multiple times. Set lives until page reload.
const _prefetchedEmails = new Set();

function usePrefetchLookup() {
  const timer = useRef(null);
  const cancel = () => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  };
  const schedule = (email) => {
    cancel();
    if (!email || _prefetchedEmails.has(email)) return;
    // 200ms hover-intent debounce — avoid firing on accidental cursor sweeps.
    timer.current = setTimeout(() => {
      _prefetchedEmails.add(email);
      apiClient
        .get("/students/lookup", { params: { email }, timeout: 30000 })
        .catch(() => _prefetchedEmails.delete(email));
    }, 200);
  };
  return { schedule, cancel };
}

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
  const { user } = useAuth();
  const canSeeEveWidget =
    user?.role === "admin"
    || (user?.board_access || []).includes("coach_activity");
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
        onRefresh={loadUtilisation}
      />

      {canSeeEveWidget && <EveCheckInsWidget />}

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

function EveCheckInsWidget() {
  const [records, setRecords] = useState(null);
  const [loading, setLoading] = useState(true);
  const [recovering, setRecovering] = useState(false);
  const [recoverReport, setRecoverReport] = useState(null);
  const [collapsed, setCollapsed] = useState(false);
  const [draftScores, setDraftScores] = useState({}); // record_id -> "1".."10"
  const [savingId, setSavingId] = useState(null);
  const version = useDeployVersion();

  const load = async () => {
    setLoading(true);
    try {
      // Fetch enough records to build a 30-day sparkline (private-tier &
      // Academy interview volumes combined rarely exceed ~10/day, so 300
      // covers 30 days with headroom).
      const { data } = await apiClient.get("/interview-eve/records", { params: { limit: 300 } });
      setRecords(data.records || []);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load eve check-ins");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const recover = async () => {
    setRecovering(true);
    setRecoverReport(null);
    try {
      const { data } = await apiClient.post("/interview-eve/backfill-scores?days=2");
      setRecoverReport(data);
      const n = (data.recovered || []).length;
      if (n > 0) {
        toast.success(`Recovered ${n} score${n > 1 ? "s" : ""}`);
      } else {
        toast.info("No new scores recovered — see breakdown");
      }
      load();
    } catch (err) {
      toast.error("Recover failed: " + (err.response?.data?.detail || err.message));
    } finally {
      setRecovering(false);
    }
  };

  const setScoreManual = async (rec) => {
    const draft = (draftScores[rec.id] || "").trim();
    const n = parseInt(draft, 10);
    if (!n || n < 1 || n > 10) {
      toast.error("Enter a number between 1 and 10");
      return;
    }
    setSavingId(rec.id);
    try {
      await apiClient.post(`/interview-eve/records/${encodeURIComponent(rec.id)}/set-score`, {
        score: n, note: "Set from Upcoming Interviews widget",
      });
      toast.success(`${rec.student_name}: ${n}/10 recorded`);
      setDraftScores((s) => ({ ...s, [rec.id]: "" }));
      load();
    } catch (err) {
      toast.error("Save failed: " + (err.response?.data?.detail || err.message));
    } finally {
      setSavingId(null);
    }
  };

  // Last 7 days view (for the cards + lists)
  const last7 = (records || []).filter((r) => {
    const sent = r.sent_at ? new Date(r.sent_at) : null;
    if (!sent) return false;
    return (Date.now() - sent.getTime()) <= 7 * 24 * 3600 * 1000;
  });

  // 30-day window (for the sparkline trend on each card)
  const last30 = (records || []).filter((r) => {
    const sent = r.sent_at ? new Date(r.sent_at) : null;
    if (!sent) return false;
    return (Date.now() - sent.getTime()) <= 30 * 24 * 3600 * 1000;
  });

  // Split replied → pre-interview (clean) vs post-interview (potentially
  // skewed because the student knows the outcome). UK calendar dates.
  const ukDate = (iso) => {
    if (!iso) return null;
    try {
      // Convert to UK day-string YYYY-MM-DD using en-CA locale (ISO-like).
      const d = new Date(iso);
      return d.toLocaleDateString("en-CA", { timeZone: "Europe/London" });
    } catch { return null; }
  };
  const classifyReply = (r) => {
    if (r.score === null || r.score === undefined) return "pending";
    const scoreDate = ukDate(r.score_received_at);
    if (!scoreDate || !r.interview_date) return "pre";
    return scoreDate > r.interview_date ? "post" : "pre";
  };

  // Group split: Premium (Private Plus + VIP + Boost & Go) vs Academy
  // (Academy + legacy Silver/Gold). Mirrors the system's `is_private_tier`
  // flag — set server-side at eve-DM send time.
  const isPremium = (r) => Boolean(r.is_private_tier);

  // Build a stats block for an arbitrary subset of records.
  const computeStats = (rows) => {
    const buckets = { pre: [], post: [], pending: [] };
    rows.forEach((r) => { buckets[classifyReply(r)].push(r); });
    const replied = [...buckets.pre, ...buckets.post];
    const preScores = buckets.pre.map((r) => r.score);
    const allScores = replied.map((r) => r.score);
    const avg = (arr) => arr.length > 0
      ? (arr.reduce((a, b) => a + b, 0) / arr.length).toFixed(1)
      : null;
    return {
      buckets,
      sent: rows.length,
      replied: replied.length,
      pending: buckets.pending.length,
      low: replied.filter((r) => r.score <= 5).length,
      avgPre: avg(preScores),
      avgAll: avg(allScores),
    };
  };

  const premiumRows = last7.filter(isPremium);
  const academyRows = last7.filter((r) => !isPremium(r));
  const statsPremium = computeStats(premiumRows);
  const statsAcademy = computeStats(academyRows);
  const stats = computeStats(last7);
  const buckets = stats.buckets;

  // 30-day daily-avg series for each group (pre-interview scores only).
  // Returns ordered array of { date: "YYYY-MM-DD", avg: number | null }.
  const buildDailySeries = (rows) => {
    const byDay = new Map();
    rows.forEach((r) => {
      if (classifyReply(r) !== "pre") return;
      const day = r.interview_date;
      if (!day) return;
      if (!byDay.has(day)) byDay.set(day, []);
      byDay.get(day).push(r.score);
    });
    // Build last-30-days timeline (inclusive of today).
    const series = [];
    const today = new Date();
    for (let i = 29; i >= 0; i -= 1) {
      const d = new Date(today);
      d.setDate(today.getDate() - i);
      const day = d.toLocaleDateString("en-CA", { timeZone: "Europe/London" });
      const scores = byDay.get(day) || [];
      series.push({
        date: day,
        avg: scores.length > 0
          ? scores.reduce((a, b) => a + b, 0) / scores.length
          : null,
        n: scores.length,
      });
    }
    return series;
  };
  const seriesPremium = buildDailySeries(last30.filter(isPremium));
  const seriesAcademy = buildDailySeries(last30.filter((r) => !isPremium(r)));

  // Combined replied / pending lists for the row display below the rollups.
  const repliedAll = [...buckets.pre, ...buckets.post];

  // Sort pending newest-first.
  const pendingRows = buckets.pending
    .slice()
    .sort((a, b) => (b.sent_at || "").localeCompare(a.sent_at || ""));
  // Sort replied by score_received_at desc.
  const repliedRows = repliedAll
    .slice()
    .sort((a, b) => (b.score_received_at || "").localeCompare(a.score_received_at || ""));

  return (
    <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-4 sm:p-5" data-testid="eve-checkins-widget">
      <div className="flex items-start justify-between gap-3 flex-wrap mb-3">
        <div className="flex items-start gap-2">
          <HeartPulse className="w-5 h-5 text-rose-600 mt-0.5" />
          <div>
            <h3 className="font-display font-bold text-lg text-[var(--ayci-ink)] leading-tight">Eve check-ins · last 7 days</h3>
            <p className="text-xs text-[var(--ayci-ink-muted)] mt-0.5">
              Auto-DMs sent at 7pm UK the night before each interview. The bot records the student's 1-10 confidence reply.
            </p>
            <div className="mt-1"><DeployBadge version={version} /></div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={recover}
            disabled={recovering || loading}
            className="text-xs font-medium px-3 py-1.5 rounded-md bg-[var(--ayci-teal)] text-white hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
            data-testid="eve-recover-scores-btn"
            title="Re-scans every pending eve-DM thread for a 1-10 score reply the bot might have missed."
          >
            <RefreshCcw className={`w-3.5 h-3.5 ${recovering ? "animate-spin" : ""}`} />
            {recovering ? "Recovering…" : "Recover missed scores"}
          </button>
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            className="text-xs text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-ink)] underline-offset-2 hover:underline"
            data-testid="eve-widget-collapse-toggle"
          >
            {collapsed ? "Expand" : "Hide details"}
          </button>
        </div>
      </div>

      {/* Tier-split rollup: Premium (Private Plus + VIP + B&G) on the left,
          Academy (incl. Silver/Gold) on the right. */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3" data-testid="eve-widget-stats">
        <GroupStatsCard
          label="Private + Boost & Go"
          colour="violet"
          stats={statsPremium}
          series30d={seriesPremium}
          testIdPrefix="eve-premium"
        />
        <GroupStatsCard
          label="Academy"
          colour="teal"
          stats={statsAcademy}
          series30d={seriesAcademy}
          testIdPrefix="eve-academy"
        />
      </div>

      {/* Recover report */}
      {recoverReport && !collapsed && (
        <div className="mb-3 bg-emerald-50/70 border border-emerald-200 rounded-md p-3 text-xs" data-testid="eve-recover-report">
          <div className="font-semibold text-emerald-900 mb-1">
            Recovery result · scanned {recoverReport.scanned}
          </div>
          {(recoverReport.recovered || []).length > 0 ? (
            <div className="text-emerald-900">
              ✅ Recovered: {recoverReport.recovered.map((r) => `${r.name} (${r.score}/10)`).join(" · ")}
            </div>
          ) : (
            <div className="text-emerald-900/70">No new scores recovered.</div>
          )}
          {(recoverReport.still_pending || []).length > 0 && (
            <div className="text-amber-900 mt-1">
              Still pending: {recoverReport.still_pending.map((r) => r.name).join(", ")}
            </div>
          )}
        </div>
      )}

      {!collapsed && (
        loading ? (
          <div className="text-xs text-[var(--ayci-ink-muted)] py-2"><Loader2 className="w-3.5 h-3.5 animate-spin inline mr-1" /> Loading records…</div>
        ) : (
          <div className="space-y-4">
            {/* Replied rows */}
            {repliedRows.length > 0 && (
              <div className="space-y-1.5" data-testid="eve-widget-replied-list">
                <div className="flex items-center justify-between gap-2 mb-1">
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ayci-ink-muted)]">
                    Replies ({repliedRows.length})
                  </div>
                  {buckets.post.length > 0 && (
                    <div className="text-[10.5px] text-amber-900 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5">
                      <strong>{buckets.post.length}</strong> reply{buckets.post.length === 1 ? "" : "ies"} came in after the interview — excluded from the average (student already knew the result)
                    </div>
                  )}
                </div>
                {repliedRows.map((rec) => {
                  const cls = classifyReply(rec);
                  const scoreColor = rec.score <= 5
                    ? "bg-rose-100 text-rose-800 border-rose-300"
                    : rec.score <= 7
                    ? "bg-amber-100 text-amber-800 border-amber-300"
                    : "bg-emerald-100 text-emerald-800 border-emerald-300";
                  const tierLabel = rec.tier || "Academy";
                  const tierIsPremium = Boolean(rec.is_private_tier);
                  return (
                    <div
                      key={rec.id}
                      className={
                        "bg-white border rounded px-3 py-2 flex items-center gap-3 flex-wrap text-xs " +
                        (cls === "post" ? "border-amber-200 bg-amber-50/30" : "border-[var(--ayci-border)]")
                      }
                      data-testid={`eve-replied-row-${rec.id}`}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-[var(--ayci-ink)] truncate flex items-center gap-1.5 flex-wrap">
                          {rec.student_name || rec.student_email}
                          <span className={
                            "text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded font-semibold " +
                            (tierIsPremium ? "bg-violet-100 text-violet-800" : "bg-teal-100 text-teal-800")
                          } title={`Tier: ${tierLabel}`}>
                            {tierLabel}
                          </span>
                          {cls === "post" ? (
                            <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-200 text-amber-900 font-semibold" title="Score arrived after the interview — could be skewed by knowing the result">
                              Post-interview
                            </span>
                          ) : (
                            <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 font-semibold" title="Score arrived before the interview — clean signal">
                              Pre
                            </span>
                          )}
                          {rec.score_set_manually_by && (
                            <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 font-semibold" title={`Set manually by ${rec.score_set_manually_by}`}>
                              Manual
                            </span>
                          )}
                        </div>
                        <div className="text-[10.5px] text-[var(--ayci-ink-muted)]">
                          Interview {rec.interview_date} · replied {rec.score_received_at ? new Date(rec.score_received_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"}
                        </div>
                      </div>
                      <span className={`text-sm font-display font-bold rounded border px-2.5 py-1 ${scoreColor}`}>
                        {rec.score}/10
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Pending rows */}
            {pendingRows.length === 0 && repliedRows.length > 0 ? (
              <div className="text-xs text-emerald-700 bg-emerald-50/70 border border-emerald-200 rounded px-3 py-2" data-testid="eve-widget-no-pending">
                ✓ No pending check-ins.
              </div>
            ) : pendingRows.length === 0 ? (
              <div className="text-xs text-emerald-700 bg-emerald-50/70 border border-emerald-200 rounded px-3 py-2" data-testid="eve-widget-no-pending">
                ✓ No pending check-ins — every student who was DM'd has either replied or is still in the response window.
              </div>
            ) : (
              <div className="space-y-1.5" data-testid="eve-widget-pending-list">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ayci-ink-muted)] mb-1">
                  Pending replies ({pendingRows.length})
                </div>
                {pendingRows.map((rec) => {
                  const tierLabel = rec.tier || "Academy";
                  const tierIsPremium = Boolean(rec.is_private_tier);
                  return (
                  <div key={rec.id} className="bg-[var(--ayci-paper)] border border-[var(--ayci-border)] rounded px-3 py-2 flex items-center gap-3 flex-wrap text-xs" data-testid={`eve-pending-row-${rec.id}`}>
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-[var(--ayci-ink)] truncate flex items-center gap-1.5 flex-wrap">
                        {rec.student_name || rec.student_email}
                        <span className={
                          "text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded font-semibold " +
                          (tierIsPremium ? "bg-violet-100 text-violet-800" : "bg-teal-100 text-teal-800")
                        } title={`Tier: ${tierLabel}`}>
                          {tierLabel}
                        </span>
                      </div>
                      <div className="text-[10.5px] text-[var(--ayci-ink-muted)]">
                        Interview {rec.interview_date} · sent {rec.sent_at ? new Date(rec.sent_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <input
                        type="number"
                        inputMode="numeric"
                        min="1" max="10"
                        placeholder="1-10"
                        value={draftScores[rec.id] || ""}
                        onChange={(e) => setDraftScores((s) => ({ ...s, [rec.id]: e.target.value }))}
                        onKeyDown={(e) => { if (e.key === "Enter") setScoreManual(rec); }}
                        className="w-16 text-xs border border-[var(--ayci-border)] rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-[var(--ayci-teal)]"
                        data-testid={`eve-score-input-${rec.id}`}
                      />
                      <button
                        type="button"
                        onClick={() => setScoreManual(rec)}
                        disabled={savingId === rec.id || !draftScores[rec.id]}
                        className="text-xs font-medium px-2.5 py-1 rounded bg-[var(--ayci-ink)] text-white hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
                        data-testid={`eve-score-save-${rec.id}`}
                        title="Manually record this student's confidence score (use when they replied with words or no number)"
                      >
                        {savingId === rec.id ? "…" : "Save"}
                      </button>
                    </div>
                  </div>
                  );
                })}
              </div>
            )}
          </div>
        )
      )}
    </div>
  );
}

function GroupStatsCard({ label, colour, stats, series30d, testIdPrefix }) {
  const palette = {
    violet: {
      border: "border-violet-200",
      bg: "bg-violet-50/40",
      header: "text-violet-900",
      avg: "text-violet-700",
      stroke: "#7c3aed",   // violet-600
      fill: "rgba(124, 58, 237, 0.12)",
    },
    teal: {
      border: "border-teal-200",
      bg: "bg-teal-50/40",
      header: "text-teal-900",
      avg: "text-teal-700",
      stroke: "#0d9488",   // teal-600
      fill: "rgba(13, 148, 136, 0.12)",
    },
  }[colour] || {
    border: "border-slate-200", bg: "bg-slate-50/40",
    header: "text-slate-900", avg: "text-slate-700",
    stroke: "#475569", fill: "rgba(71, 85, 105, 0.12)",
  };
  const postCount = stats.buckets.post.length;

  // Trend: compare the most-recent 15 days' avg to the prior 15 days'.
  // Only meaningful when both halves have at least 1 data point.
  const series = series30d || [];
  const split = Math.floor(series.length / 2);
  const lo = series.slice(0, split).filter((p) => p.avg !== null);
  const hi = series.slice(split).filter((p) => p.avg !== null);
  const mean = (xs) => xs.length > 0
    ? xs.reduce((a, b) => a + b.avg, 0) / xs.length : null;
  const meanLo = mean(lo);
  const meanHi = mean(hi);
  const delta = (meanLo !== null && meanHi !== null)
    ? meanHi - meanLo : null;
  const trendArrow = delta === null
    ? null
    : delta > 0.1 ? "up"
    : delta < -0.1 ? "down"
    : "flat";

  return (
    <div className={`rounded-md border ${palette.border} ${palette.bg} p-3`} data-testid={`${testIdPrefix}-card`}>
      <div className={`text-xs font-semibold uppercase tracking-wider ${palette.header} mb-2 flex items-center justify-between gap-2 flex-wrap`}>
        <span>{label}</span>
        {trendArrow && (
          <span
            className={
              "inline-flex items-center gap-1 text-[10px] normal-case font-medium px-1.5 py-0.5 rounded " +
              (trendArrow === "up"
                ? "bg-emerald-100 text-emerald-800"
                : trendArrow === "down"
                ? "bg-rose-100 text-rose-800"
                : "bg-slate-100 text-slate-700")
            }
            title="30-day trend (recent 15 days vs prior 15 days, pre-interview avg)"
            data-testid={`${testIdPrefix}-trend`}
          >
            {trendArrow === "up" ? "▲" : trendArrow === "down" ? "▼" : "→"}
            {delta !== null && ` ${delta > 0 ? "+" : ""}${delta.toFixed(1)}`}
          </span>
        )}
      </div>
      <div className="grid grid-cols-5 gap-1.5 items-baseline">
        <MiniStat label="Sent" value={stats.sent} accent="text-slate-700" testid={`${testIdPrefix}-sent`} />
        <MiniStat label="Replied" value={stats.replied} accent="text-emerald-700" testid={`${testIdPrefix}-replied`} />
        <MiniStat label="Pending" value={stats.pending} accent={stats.pending > 0 ? "text-amber-700" : "text-slate-500"} testid={`${testIdPrefix}-pending`} />
        <MiniStat label="Low ≤5" value={stats.low} accent={stats.low > 0 ? "text-rose-700" : "text-slate-500"} testid={`${testIdPrefix}-low`} />
        <MiniStat
          label={stats.avgAll && postCount > 0 ? "Avg · pre" : "Avg"}
          value={stats.avgPre ? `${stats.avgPre}` : "—"}
          accent={palette.avg}
          big
          sublabel={stats.avgAll && postCount > 0 ? `inc post ${stats.avgAll}` : null}
          testid={`${testIdPrefix}-avg`}
        />
      </div>
      <Sparkline series={series} stroke={palette.stroke} fill={palette.fill} testid={`${testIdPrefix}-sparkline`} />
    </div>
  );
}

function Sparkline({ series, stroke, fill, testid }) {
  const valid = (series || []).filter((p) => p.avg !== null);
  if (valid.length < 2) {
    return (
      <div className="mt-2 h-7 flex items-center justify-center text-[10px] text-[var(--ayci-ink-muted)] italic" data-testid={testid}>
        Not enough data for 30-day trend yet
      </div>
    );
  }
  const W = 280;
  const H = 28;
  const PAD = 2;
  // Y range: 1–10 (full score range, so trends stay visually comparable
  // across both cards even if one has a tight cluster).
  const yMin = 1;
  const yMax = 10;
  const y = (v) => H - PAD - ((v - yMin) / (yMax - yMin)) * (H - PAD * 2);
  // X: stretch across the full 30-day axis, evenly spaced day-by-day.
  // Skipping nulls visually so the line jumps the gap.
  const n = series.length;
  const x = (i) => PAD + (i / Math.max(n - 1, 1)) * (W - PAD * 2);
  // Build a single polyline that breaks at null gaps using "M" / "L".
  let d = "";
  let lastWasNull = true;
  series.forEach((p, i) => {
    if (p.avg === null) { lastWasNull = true; return; }
    const cmd = lastWasNull ? "M" : "L";
    d += `${cmd}${x(i).toFixed(1)},${y(p.avg).toFixed(1)} `;
    lastWasNull = false;
  });
  // Endpoint dot (most recent valid point).
  let endX = null;
  let endY = null;
  for (let i = series.length - 1; i >= 0; i -= 1) {
    if (series[i].avg !== null) {
      endX = x(i); endY = y(series[i].avg); break;
    }
  }
  return (
    <div className="mt-2" data-testid={testid}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full h-7" aria-hidden>
        {/* Reference line at 7 (the team's typical confidence floor) */}
        <line
          x1={PAD} x2={W - PAD}
          y1={y(7)} y2={y(7)}
          stroke={stroke} strokeOpacity="0.18" strokeDasharray="2 2" strokeWidth="0.6"
        />
        {/* Fill under curve — visual weight, optional */}
        {valid.length > 1 && (
          <path
            d={d + `L${(endX || 0).toFixed(1)},${H - PAD} L${(x(series.findIndex((p) => p.avg !== null)) || PAD).toFixed(1)},${H - PAD} Z`}
            fill={fill}
            stroke="none"
          />
        )}
        <path d={d.trim()} fill="none" stroke={stroke} strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />
        {endX !== null && (
          <circle cx={endX} cy={endY} r="1.7" fill={stroke} />
        )}
      </svg>
      <div className="text-[9.5px] text-[var(--ayci-ink-muted)] mt-0.5 flex items-center justify-between">
        <span>30 days · pre-interview avg</span>
        <span>{valid.length} day{valid.length === 1 ? "" : "s"} with replies</span>
      </div>
    </div>
  );
}

function MiniStat({ label, value, accent, big, sublabel, testid }) {
  return (
    <div className="text-center" data-testid={testid}>
      <div className={`font-display font-bold ${accent} ${big ? "text-2xl" : "text-lg"}`}>{value}</div>
      <div className="text-[9.5px] uppercase tracking-wider text-[var(--ayci-ink-muted)] leading-tight">{label}</div>
      {sublabel && (
        <div className="text-[9px] text-[var(--ayci-ink-muted)] leading-tight">{sublabel}</div>
      )}
    </div>
  );
}

function AcademyRow({ student, today }) {
  const prefetch = usePrefetchLookup();
  return (
    <li
      className="bg-white border border-[var(--ayci-border)] rounded-lg px-4 py-3 flex items-center justify-between gap-3 hover:shadow-sm transition-shadow"
      data-testid={`academy-row-${student.id}`}
      onMouseEnter={() => student.email && prefetch.schedule(student.email)}
      onMouseLeave={prefetch.cancel}
    >
      <div className="flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          {student.email ? (
            <Link
              to={`/students?email=${encodeURIComponent(student.email)}`}
              className="font-semibold text-[var(--ayci-ink)] hover:text-[var(--ayci-teal)]"
              title="Open Student Lookup"
              data-testid={`academy-lookup-link-${student.email}`}
            >
              {student.name}
            </Link>
          ) : (
            <span className="font-semibold text-[var(--ayci-ink)]">{student.name}</span>
          )}
          {student.monday_url && (
            <a
              href={student.monday_url}
              target="_blank"
              rel="noreferrer"
              className="opacity-50 hover:opacity-100 text-[var(--ayci-teal)]"
              title="Open in Monday"
              data-testid={`academy-monday-link-${student.id}`}
            >
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
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
  const prefetch = usePrefetchLookup();
  const { calls_30min: calls, mock_interviews: mocks, bonus_calls: bonus, videos } = student;
  return (
    <li
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-4 shadow-sm"
      data-testid={`private-card-${student.id}`}
      onMouseEnter={() => student.email && prefetch.schedule(student.email)}
      onMouseLeave={prefetch.cancel}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {student.email ? (
              <Link
                to={`/students?email=${encodeURIComponent(student.email)}`}
                className="font-display font-semibold text-base text-[var(--ayci-ink)] hover:text-[var(--ayci-teal)]"
                title="Open Student Lookup"
                data-testid={`private-lookup-link-${student.email}`}
              >
                {student.name}
              </Link>
            ) : (
              <span className="font-display font-semibold text-base text-[var(--ayci-ink)]">
                {student.name}
              </span>
            )}
            {student.monday_url && (
              <a
                href={student.monday_url}
                target="_blank"
                rel="noreferrer"
                className="opacity-50 hover:opacity-100 text-[var(--ayci-teal)]"
                title="Open in Monday"
                data-testid={`private-monday-link-${student.id}`}
              >
                <ExternalLink className="w-3.5 h-3.5" />
              </a>
            )}
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
function UtilisationSection({ utilisation, loading, days, onRefresh }) {
  const [logOpen, setLogOpen] = useState(false);
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
          <div className="flex gap-2 flex-wrap items-center">
            <button
              type="button"
              onClick={() => setLogOpen(true)}
              className="text-xs font-medium px-3 py-1.5 rounded-md bg-white border border-violet-300 text-violet-800 hover:bg-violet-50 flex items-center gap-1.5 shadow-sm"
              data-testid="log-extra-call-btn"
              title="Record a 1:1 call that wasn't booked through Calendly. It will count towards the student's call allowance."
            >
              <Plus className="w-3.5 h-3.5" />
              Log extra call
            </button>
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

      <LogExtraCallDialog
        open={logOpen}
        onOpenChange={setLogOpen}
        students={[...(flagged || []), ...(onTrack || [])]}
        onSaved={() => {
          setLogOpen(false);
          onRefresh && onRefresh();
        }}
      />

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


function LogExtraCallDialog({ open, onOpenChange, students, onSaved }) {
  const { user } = useAuth();
  const [studentId, setStudentId] = useState("");
  const [emailOverride, setEmailOverride] = useState("");
  const [nameOverride, setNameOverride] = useState("");
  const [host, setHost] = useState("");
  const [minutes, setMinutes] = useState(30);
  const [happenedAt, setHappenedAt] = useState("");
  const [notes, setNotes] = useState("");
  const [recent, setRecent] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open && !happenedAt) {
      const d = new Date();
      const pad = (n) => String(n).padStart(2, "0");
      setHappenedAt(
        `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`,
      );
    }
    if (open && !host) {
      setHost((user?.name || "").trim());
    }
    if (open) {
      apiClient
        .get("/today-calls")
        .then(({ data }) => {
          const manuals = (data.items || []).filter((c) => c.source === "manual");
          setRecent(manuals.slice(0, 5));
        })
        .catch(() => setRecent([]));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const studentOptions = (students || [])
    .map((s) => ({
      key: `${s.monday_id}|${s.email}|${s.name}`,
      label: `${s.name}${s.tier ? ` (${s.tier})` : ""}`,
      email: s.email,
      name: s.name,
    }))
    .sort((a, b) => a.label.localeCompare(b.label));

  const isCustom = studentId === "__custom__";

  const submit = async () => {
    const selected = studentOptions.find((o) => o.key === studentId);
    const finalEmail = isCustom ? (emailOverride || "").trim().toLowerCase() : selected?.email;
    const finalName = isCustom ? (nameOverride || "").trim() : selected?.name;
    if (!finalEmail || !finalEmail.includes("@")) {
      toast.error("Pick a student or enter a valid email");
      return;
    }
    if (!finalName) {
      toast.error("Student name is required");
      return;
    }
    if (!host.trim()) {
      toast.error("Who ran the call?");
      return;
    }
    if (!happenedAt) {
      toast.error("When did the call happen?");
      return;
    }
    let startsAtIso;
    try {
      startsAtIso = new Date(happenedAt).toISOString();
    } catch {
      toast.error("Invalid date/time");
      return;
    }
    setSaving(true);
    try {
      await apiClient.post("/today-calls/manual", {
        student_name: finalName,
        student_email: finalEmail,
        host: host.trim(),
        starts_at: startsAtIso,
        duration_min: minutes,
        notes: notes || null,
      });
      toast.success(
        `Logged ${minutes}-min call for ${finalName} — counts as 1 call`,
      );
      setStudentId("");
      setEmailOverride("");
      setNameOverride("");
      setMinutes(30);
      setNotes("");
      onSaved && onSaved();
    } catch (err) {
      toast.error("Save failed: " + (err.response?.data?.detail || err.message));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" data-testid="log-extra-call-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <PhoneCall className="w-4 h-4 text-violet-700" />
            Log extra call
          </DialogTitle>
          <DialogDescription>
            Records a 1:1 call that wasn't booked through Calendly. <strong>Counts as one call</strong> towards the student's allowance, no matter the length. (Tier allowances are call-events, not minutes — VIP = 4×30 + 1×60-min mock = 5 calls; Private Plus = 1 call; bonus calls = 1 each.) Duration is logged for the audit trail.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <label className="text-xs font-semibold text-[var(--ayci-ink)] mb-1 block">Student</label>
            <select
              value={studentId}
              onChange={(e) => setStudentId(e.target.value)}
              className="w-full text-sm border border-[var(--ayci-border)] rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-violet-500"
              data-testid="log-call-student-select"
            >
              <option value="">— Select a private-tier student —</option>
              {studentOptions.map((o) => (
                <option key={o.key} value={o.key}>{o.label}</option>
              ))}
              <option value="__custom__">+ Other student (type email)</option>
            </select>
            {isCustom && (
              <div className="grid grid-cols-2 gap-2 mt-2">
                <input
                  type="text"
                  value={nameOverride}
                  onChange={(e) => setNameOverride(e.target.value)}
                  placeholder="Student name"
                  className="text-sm border border-[var(--ayci-border)] rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-violet-500"
                  data-testid="log-call-custom-name"
                />
                <input
                  type="email"
                  value={emailOverride}
                  onChange={(e) => setEmailOverride(e.target.value)}
                  placeholder="student@example.com"
                  className="text-sm border border-[var(--ayci-border)] rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-violet-500"
                  data-testid="log-call-custom-email"
                />
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-[var(--ayci-ink)] mb-1 block">Duration</label>
              <div className="flex gap-1.5" data-testid="log-call-minutes-group">
                {[30, 45, 60, 90].map((m) => (
                  <button
                    key={m} type="button"
                    onClick={() => setMinutes(m)}
                    className={
                      "flex-1 text-xs font-semibold rounded px-2 py-1.5 border " +
                      (minutes === m
                        ? "bg-violet-600 text-white border-violet-700"
                        : "bg-white text-[var(--ayci-ink)] border-[var(--ayci-border)] hover:bg-violet-50")
                    }
                    data-testid={`log-call-minutes-${m}`}
                  >
                    {m}m
                  </button>
                ))}
              </div>
              <div className="text-[10.5px] text-[var(--ayci-ink-muted)] mt-1">
                Logged for the audit trail · counts as <strong>1 call</strong>
              </div>
            </div>
            <div>
              <label className="text-xs font-semibold text-[var(--ayci-ink)] mb-1 block">Coach / host</label>
              <input
                type="text"
                value={host}
                onChange={(e) => setHost(e.target.value)}
                placeholder="Tessa"
                className="w-full text-sm border border-[var(--ayci-border)] rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-violet-500"
                data-testid="log-call-host"
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-[var(--ayci-ink)] mb-1 block">When did the call happen?</label>
            <input
              type="datetime-local"
              value={happenedAt}
              onChange={(e) => setHappenedAt(e.target.value)}
              className="w-full text-sm border border-[var(--ayci-border)] rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-violet-500"
              data-testid="log-call-happened-at"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-[var(--ayci-ink)] mb-1 block">Notes (optional)</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="e.g. Extra session by request, ran 60 min — student kindly bumped allowance"
              rows={2}
              maxLength={500}
              className="w-full text-sm border border-[var(--ayci-border)] rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-violet-500"
              data-testid="log-call-notes"
            />
          </div>

          {recent.length > 0 && (
            <details className="text-xs">
              <summary className="cursor-pointer text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-ink)]">
                Recent manual entries ({recent.length})
              </summary>
              <ul className="mt-1 space-y-1">
                {recent.map((r) => (
                  <li key={r.id} className="text-[11px] text-[var(--ayci-ink-muted)] truncate" title={r.notes || ""}>
                    <span className="font-semibold text-[var(--ayci-ink)]">{r.student_name}</span> · {r.duration_min}m with {r.host} · {new Date(r.starts_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>

        <DialogFooter className="gap-2">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="text-xs font-medium px-3 py-1.5 rounded border border-[var(--ayci-border)] text-[var(--ayci-ink)] hover:bg-slate-50"
            data-testid="log-call-cancel-btn"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={saving}
            className="text-xs font-medium px-3 py-1.5 rounded bg-violet-700 text-white hover:bg-violet-800 disabled:opacity-50 disabled:cursor-not-allowed"
            data-testid="log-call-save-btn"
          >
            {saving ? "Saving…" : "Log call"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
