import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Calendar,
  Loader2,
  RefreshCw,
  ExternalLink,
  AlertCircle,
  Clock,
  Users,
  Award,
  Send,
  Check,
  UserPlus,
  History as HistoryIcon,
  Star,
  Plus,
  X,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import HeroBanner, { HERO_PRESETS } from "@/components/HeroBanner";

const SESSION_LABEL = {
  curriculum: "Curriculum",
  group_coaching: "Group Coaching",
};

const SESSION_BADGE = {
  curriculum: "bg-violet-50 text-violet-700 border-violet-200",
  group_coaching: "bg-emerald-50 text-emerald-700 border-emerald-200",
};

const STATUS_OPTIONS = [
  { value: "spotlighted", label: "Spotlighted", chip: "bg-emerald-100 text-emerald-800 border-emerald-300", icon: Star },
  { value: "didnt_attend", label: "Didn't attend", chip: "bg-slate-100 text-slate-700 border-slate-300", icon: X },
  { value: "skipped", label: "Skipped", chip: "bg-amber-100 text-amber-800 border-amber-300", icon: AlertCircle },
  { value: "not_submitted_correctly", label: "Not submitted correctly", chip: "bg-rose-100 text-rose-800 border-rose-300", icon: AlertCircle },
];

const STATUS_META = Object.fromEntries(STATUS_OPTIONS.map((s) => [s.value, s]));

function formatUkDateTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/London",
  });
}

function relativeTimePhrase(iso) {
  if (!iso) return null;
  const start = new Date(iso).getTime();
  const now = Date.now();
  const min = Math.round((start - now) / 60000);
  if (Math.abs(min) < 1) return { text: "starting now", tone: "emerald" };
  if (min > 0) {
    if (min >= 90) return { text: `starts in ${(min / 60).toFixed(1)} h`, tone: "slate" };
    if (min >= 60) return { text: `starts in ${Math.round(min / 60)} h`, tone: "slate" };
    return { text: `starts in ${min} min`, tone: min <= 30 ? "amber" : "slate" };
  }
  const ago = -min;
  const end = iso ? new Date(iso).getTime() + 2 * 3600 * 1000 : 0;
  const inProgress = end > now;
  if (inProgress) return { text: `in progress · started ${ago} min ago`, tone: "emerald" };
  if (ago >= 90) return { text: `started ${(ago / 60).toFixed(1)} h ago`, tone: "slate" };
  return { text: `started ${ago} min ago`, tone: "slate" };
}

function formatDate(iso) {
  if (!iso) return "-";
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

export default function SpotlightCoaching() {
  const [tab, setTab] = useState("upcoming");
  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="spotlight-page">
      <HeroBanner
        {...(HERO_PRESETS.spotlight || HERO_PRESETS.cohort)}
        eyebrow="Coach prep"
        title="Spotlight Coaching"
        subtitle="The next live sessions, the people who've put themselves forward, and who has an interview coming up."
        testid="spotlight-hero"
      />

      <div className="flex items-center gap-1 border-b border-[var(--ayci-border)]" data-testid="spotlight-tabs">
        {[
          { id: "upcoming", label: "Upcoming sessions", icon: Calendar },
          { id: "history", label: "History", icon: HistoryIcon },
        ].map((t) => {
          const Icon = t.icon;
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              data-testid={`spotlight-tab-${t.id}`}
              className={
                "inline-flex items-center gap-2 px-4 py-2.5 text-sm border-b-2 -mb-px transition-colors " +
                (active
                  ? "border-[var(--ayci-teal)] text-[var(--ayci-teal)] font-semibold"
                  : "border-transparent text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-ink)]")
              }
            >
              <Icon className="w-4 h-4" />
              {t.label}
            </button>
          );
        })}
      </div>

      {tab === "upcoming" ? <UpcomingView /> : <HistoryView />}
    </div>
  );
}

// ============================================================================
// UPCOMING VIEW
// ============================================================================

function UpcomingView() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/spotlight/sessions", {
        params: { limit: 4 },
        timeout: 60000,
      });
      setData(data);
    } catch (e) {
      toast.error(
        formatApiErrorDetail(e.response?.data?.detail) || "Failed to load Spotlight sessions"
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  // Optimistic local mutation for outcome marks - keeps the UI instant. The
  // background POST still hits the server; on failure OutcomePicker calls
  // `load` to resync.
  const applyLocalUpdate = ({
    sessionId, studentName, studentEmail, recordId, status, removed,
  }) => {
    setData((prev) => {
      if (!prev) return prev;
      const nameKey = (studentName || "").trim().toLowerCase();
      const emailKey = (studentEmail || "").trim().toLowerCase();
      return {
        ...prev,
        sessions: (prev.sessions || []).map((s) => {
          if (s.id !== sessionId) return s;
          const students = (s.students || []).map((st) => {
            const matchEmail =
              emailKey && (st.email || "").toLowerCase() === emailKey;
            const matchName = (st.name || "").trim().toLowerCase() === nameKey;
            if (matchEmail || matchName) {
              if (removed) {
                return { ...st, record_status: null, record: null };
              }
              return {
                ...st,
                record_status: status,
                record: { ...(st.record || {}), id: recordId, status },
              };
            }
            return st;
          });
          let records = s.records || [];
          if (removed) {
            records = records.filter((r) => r.id !== recordId);
          } else if (recordId) {
            records = records.map((r) =>
              r.id === recordId ? { ...r, status } : r,
            );
          }
          return { ...s, students, records };
        }),
      };
    });
  };

  const sessions = data?.sessions || [];

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <Button variant="outline" onClick={load} disabled={loading} data-testid="spotlight-refresh" size="sm">
          {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
          Refresh
        </Button>
      </div>

      {loading && !data && (
        <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-8 text-center text-[var(--ayci-ink-muted)]">
          <Loader2 className="w-6 h-6 animate-spin mx-auto mb-3 text-[var(--ayci-teal)]" />
          Loading next sessions from Circle…
        </div>
      )}

      {data && sessions.length === 0 && (
        <div
          className="bg-white border border-[var(--ayci-border)] rounded-lg p-8 text-center text-[var(--ayci-ink-muted)]"
          data-testid="spotlight-empty"
        >
          <Calendar className="w-6 h-6 mx-auto mb-3 text-[var(--ayci-ink-muted)]" />
          {data.note || "No upcoming Curriculum or General Coaching sessions found."}
        </div>
      )}

      {sessions.map((s, idx) => (
        <SessionCard
          key={`${s.id}-${idx}`}
          session={s}
          primary={idx === 0}
          onRecordsChange={load}
          onLocalUpdate={applyLocalUpdate}
        />
      ))}
    </div>
  );
}

function SessionCard({ session, primary, onRecordsChange, onLocalUpdate }) {
  const label = SESSION_LABEL[session.session_type] || "Session";
  const badge = SESSION_BADGE[session.session_type] || "bg-slate-50 text-slate-700 border-slate-200";
  const [sending, setSending] = useState(false);
  const [addingManual, setAddingManual] = useState(false);

  const sendSlackPreview = async () => {
    setSending(true);
    try {
      const { data } = await apiClient.post(`/spotlight/slack/test`, null, {
        params: { session_id: session.id },
        timeout: 30000,
      });
      if (data.sent) {
        toast.success("Slack preview sent - check your channel");
      } else {
        toast.error(data.reason || data.error || "Slack send failed - is SLACK_WEBHOOK_URL set?");
      }
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to send");
    } finally {
      setSending(false);
    }
  };

  // Build a combined list: tally students + any manual records not matching a tally row
  const tallyKeys = new Set((session.students || []).map((st) => (st.name || "").trim().toLowerCase()));
  const manualRecords = (session.records || []).filter(
    (r) => !tallyKeys.has((r.student_name || "").trim().toLowerCase())
  );

  return (
    <section
      className={
        "bg-white border rounded-lg shadow-sm overflow-hidden " +
        (primary ? "border-[var(--ayci-teal)] shadow-md" : "border-[var(--ayci-border)]")
      }
      data-testid={`spotlight-session-${session.id}`}
    >
      <div
        className={
          "px-5 py-4 border-b border-[var(--ayci-border)] " +
          (primary ? "bg-gradient-to-r from-violet-50 via-fuchsia-50 to-sky-50" : "bg-slate-50/50")
        }
      >
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <span
                className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full border font-semibold ${badge}`}
                data-testid={`spotlight-session-type-${session.id}`}
              >
                {label}
              </span>
              {primary && (
                <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full bg-[var(--ayci-teal)] text-white font-semibold">
                  Next up
                </span>
              )}
            </div>
            <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)] leading-tight">{session.name}</h2>
            <div className="flex items-center gap-3 mt-1.5 text-xs text-[var(--ayci-ink-muted)] flex-wrap">
              <span className="inline-flex items-center gap-1.5">
                <Calendar className="w-3.5 h-3.5" />
                {formatUkDateTime(session.starts_at)} (UK)
              </span>
              {(() => {
                const rel = relativeTimePhrase(session.starts_at);
                if (!rel) return null;
                const tones = {
                  emerald: "bg-emerald-50 text-emerald-800 border-emerald-200",
                  amber: "bg-amber-50 text-amber-800 border-amber-200",
                  slate: "bg-slate-50 text-slate-700 border-slate-200",
                };
                return (
                  <span
                    className={`inline-flex items-center gap-1 text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border font-semibold ${tones[rel.tone]}`}
                    data-testid={`spotlight-relative-${session.id}`}
                  >
                    {rel.text}
                  </span>
                );
              })()}
              {session.deadline_uk_date && (
                <span className="inline-flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5" />
                  Eligible only if submitted: {formatDate(session.deadline_uk_date)}
                </span>
              )}
              {session.circle_url && (
                <a
                  href={session.circle_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-[var(--ayci-teal)] hover:underline"
                  data-testid={`spotlight-circle-link-${session.id}`}
                >
                  Open in Circle <ExternalLink className="w-3 h-3" />
                </a>
              )}
            </div>
          </div>
          <div className="flex items-center gap-3 shrink-0 flex-wrap">
            <Stat label="Submissions" value={session.submissions_total} testid={`spotlight-stat-total-${session.id}`} />
            <Stat
              label="Interview soon"
              value={session.with_interview_total}
              tone={session.with_interview_total > 0 ? "rose" : "slate"}
              testid={`spotlight-stat-interviews-${session.id}`}
            />
            <button
              onClick={sendSlackPreview}
              disabled={sending}
              data-testid={`spotlight-slack-preview-${session.id}`}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded text-[11px] font-semibold border border-[var(--ayci-border)] bg-white hover:border-[var(--ayci-teal)] hover:text-[var(--ayci-teal)] transition-colors disabled:opacity-50"
              title="Send a preview of this session's reminder to Slack right now"
            >
              {sending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />}
              {sending ? "Sending…" : "Slack preview"}
            </button>
          </div>
        </div>
      </div>

      {(session.students?.length || 0) === 0 && manualRecords.length === 0 ? (
        <div
          className="p-6 text-center text-sm text-[var(--ayci-ink-muted)]"
          data-testid={`spotlight-students-empty-${session.id}`}
        >
          <Users className="w-5 h-5 mx-auto mb-2 text-[var(--ayci-ink-muted)]" />
          No spotlight submissions yet for this session.
        </div>
      ) : (
        <>
          <div
            className="px-4 py-2 bg-amber-50/40 border-b border-amber-100 text-[11px] text-[var(--ayci-ink-muted)] flex items-center gap-2 flex-wrap"
            data-testid={`spotlight-priority-caption-${session.id}`}
          >
            <span className="font-semibold uppercase tracking-wider text-amber-800">
              How this list is prioritised:
            </span>
            <span>
              1. Interview soonest <span className="text-rose-600 font-semibold">·</span> 2. Most badges (leaderboard rank) <span className="text-rose-600 font-semibold">·</span> 3. Earliest eligible submission
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] border-b border-[var(--ayci-border)]">
                  <th className="px-4 py-2 font-semibold w-[1%] whitespace-nowrap">#</th>
                  <th className="px-4 py-2 font-semibold">Student</th>
                  <th className="px-4 py-2 font-semibold">Topic</th>
                  <th className="px-3 py-2 font-semibold whitespace-nowrap">Interview</th>
                  <th className="px-3 py-2 font-semibold whitespace-nowrap">Submitted</th>
                  <th className="px-3 py-2 font-semibold whitespace-nowrap">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {(session.students || []).map((st, i) => (
                  <StudentRow
                    key={`${st.name}-${st.submitted_at}-${i}`}
                    student={st}
                    index={i}
                    session={session}
                    onRecordsChange={onRecordsChange}
                    onLocalUpdate={onLocalUpdate}
                  />
                ))}
                {manualRecords.map((r, i) => (
                  <ManualRow
                    key={r.id}
                    record={r}
                    index={(session.students?.length || 0) + i}
                    session={session}
                    onRecordsChange={onRecordsChange}
                    onLocalUpdate={onLocalUpdate}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <div className="px-4 py-3 border-t border-[var(--ayci-border)] bg-slate-50/40">
        {addingManual ? (
          <ManualAddForm
            session={session}
            onClose={() => setAddingManual(false)}
            onDone={() => {
              setAddingManual(false);
              onRecordsChange?.();
            }}
          />
        ) : (
          <button
            onClick={() => setAddingManual(true)}
            data-testid={`spotlight-add-manual-${session.id}`}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-[var(--ayci-teal)] hover:underline"
          >
            <UserPlus className="w-3.5 h-3.5" /> Add someone not on this list
          </button>
        )}
      </div>
    </section>
  );
}

function StudentRow({ student, index, session, onRecordsChange, onLocalUpdate }) {
  const days = student.days_until_interview;
  const interviewSoon = days !== null && days !== undefined && days <= 7;
  const lbRank = student.leaderboard_rank;
  const cohortRank = student.cohort_leaderboard_rank;
  // Only flag as "top of leaderboard" when they're genuinely in the cohort
  // top 10 - earlier this was using session-local rank which gave misleading
  // "#1 leaderboard" chips for students who were actually rank #33 cohort-wide.
  const topLeaderboard = cohortRank && cohortRank <= 3;
  // Highlight top 3 rows of the table itself with a gold left-border so the
  // priority is unmistakable at a glance.
  const topPriority = index < 3;
  const rowClass = interviewSoon
    ? "bg-rose-50/40 hover:bg-rose-50/70"
    : topPriority
      ? "bg-amber-50/30 hover:bg-amber-50/50"
      : "hover:bg-slate-50/50";
  const borderClass = topPriority && !interviewSoon ? "border-l-4 border-l-amber-400" : "";
  return (
    <tr
      className={`border-b border-[var(--ayci-border)] last:border-b-0 ${rowClass} ${borderClass}`}
      data-testid={`spotlight-row-${session.id}-${index}`}
    >
      <td className="px-4 py-3 whitespace-nowrap">
        <div
          className={
            "inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold " +
            (interviewSoon
              ? "bg-rose-600 text-white"
              : topPriority
                ? "bg-amber-400 text-amber-950"
                : "bg-slate-100 text-[var(--ayci-ink)]")
          }
        >
          {index + 1}
        </div>
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-[var(--ayci-ink)]">{student.name}</span>
          {topLeaderboard ? (
            <LeaderboardRankPill rank={cohortRank} score={student.leaderboard_score} />
          ) : (
            student.leaderboard_score != null && student.leaderboard_score > 0 && (
              <span
                className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200 font-semibold tabular-nums"
                title={`${student.leaderboard_score} Circle badges (cohort/tier badges excluded)`}
              >
                <Award className="w-3 h-3" />
                {student.leaderboard_score} badges
              </span>
            )
          )}
          {student.spotlight_count > 0 && (
            <span
              className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-violet-50 text-violet-700 border border-violet-200 font-semibold tabular-nums"
              title={`Spotlighted ${student.spotlight_count} time${student.spotlight_count === 1 ? "" : "s"} before`}
              data-testid={`spotlight-count-${session.id}-${index}`}
            >
              <Star className="w-3 h-3 fill-current" />
              {student.spotlight_count}×
            </span>
          )}
        </div>
        {topPriority && (
          <PriorityReason student={student} index={index} />
        )}
        {!student.eligible && student.eligibility === "late" && (
          <span
            className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-200 font-semibold mt-1"
            title={`Submitted ${student.submitted_uk_date}, after the deadline (${session.deadline_uk_date})`}
          >
            <AlertCircle className="w-3 h-3" /> Late
          </span>
        )}
        {!student.eligible && student.eligibility === "early" && (
          <span
            className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200 font-semibold mt-1"
            title={`Submitted ${student.submitted_uk_date} - needs to be the day before (${session.deadline_uk_date})`}
          >
            <AlertCircle className="w-3 h-3" /> Early
          </span>
        )}
      </td>
      <td className="px-4 py-3 text-[var(--ayci-ink)] max-w-[440px]">
        <div className="whitespace-pre-wrap break-words">
          {student.topic || <span className="text-[var(--ayci-ink-muted)] italic">(no topic given)</span>}
        </div>
      </td>
      <td className="px-3 py-3 whitespace-nowrap">
        {student.interview_date ? (
          <div>
            <div className={"font-semibold tabular-nums " + (interviewSoon ? "text-rose-700" : "text-[var(--ayci-ink)]")}>
              {formatDate(student.interview_date)}
            </div>
            <div className="text-[10px] text-[var(--ayci-ink-muted)]">
              in {days} day{days === 1 ? "" : "s"}
              {student.interview_type ? ` · ${student.interview_type}` : ""}
            </div>
          </div>
        ) : student.claims_interview ? (
          <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200 font-semibold">
            Form not done
          </span>
        ) : (
          <span className="text-xs text-[var(--ayci-ink-muted)]">-</span>
        )}
      </td>
      <td className="px-3 py-3 text-xs text-[var(--ayci-ink-muted)] whitespace-nowrap tabular-nums">
        {formatDate(student.submitted_uk_date)}
      </td>
      <td className="px-3 py-3 whitespace-nowrap">
        <OutcomePicker
          sessionId={session.id}
          studentName={student.name}
          studentEmail={student.email}
          currentStatus={student.record_status}
          recordId={student.record?.id}
          source="tally"
          onDone={onRecordsChange}
          onLocalUpdate={onLocalUpdate}
          testid={`spotlight-outcome-${session.id}-${index}`}
        />
      </td>
    </tr>
  );
}

function ManualRow({ record, index, session, onRecordsChange, onLocalUpdate }) {
  return (
    <tr
      className="border-b border-[var(--ayci-border)] last:border-b-0 bg-violet-50/30 hover:bg-violet-50/50"
      data-testid={`spotlight-manual-row-${session.id}-${index}`}
    >
      <td className="px-4 py-3 whitespace-nowrap">
        <div className="inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold bg-violet-100 text-violet-800">
          +
        </div>
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-[var(--ayci-ink)]">{record.student_name}</span>
          <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-violet-100 text-violet-800 border border-violet-200 font-semibold">
            Manual
          </span>
        </div>
      </td>
      <td className="px-4 py-3 text-[var(--ayci-ink-muted)] italic text-xs max-w-[440px]">
        {record.notes || "(added by coach)"}
      </td>
      <td className="px-3 py-3 text-xs text-[var(--ayci-ink-muted)]">-</td>
      <td className="px-3 py-3 text-xs text-[var(--ayci-ink-muted)]">-</td>
      <td className="px-3 py-3 whitespace-nowrap">
        <OutcomePicker
          sessionId={session.id}
          studentName={record.student_name}
          currentStatus={record.status}
          recordId={record.id}
          source="manual"
          allowDelete
          onDone={onRecordsChange}
          onLocalUpdate={onLocalUpdate}
          testid={`spotlight-outcome-manual-${session.id}-${index}`}
        />
      </td>
    </tr>
  );
}

function OutcomePicker({
  sessionId,
  studentName,
  studentEmail,
  currentStatus,
  recordId,
  source = "tally",
  allowDelete = false,
  onDone,
  onLocalUpdate,
  testid,
}) {
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const current = currentStatus ? STATUS_META[currentStatus] : null;

  const save = async (status) => {
    setSaving(true);
    setOpen(false);
    // Optimistic UI: flip the chip immediately so the team can move on. The
    // network call still happens in the background; if it fails we revert and
    // surface a toast.
    const previousStatus = currentStatus;
    onLocalUpdate?.({
      sessionId,
      studentName,
      studentEmail,
      recordId,
      source,
      status,
    });
    try {
      const { data } = await apiClient.post(`/spotlight/records`, {
        session_id: sessionId,
        student_name: studentName,
        student_email: studentEmail,
        status,
        source,
      });
      // Confirm with the real recordId from the server (in case it was new)
      if (data && data.id) {
        onLocalUpdate?.({
          sessionId,
          studentName,
          studentEmail,
          recordId: data.id,
          source,
          status,
          confirmed: true,
        });
      }
      toast.success(`Marked ${studentName} as ${STATUS_META[status].label.toLowerCase()}`);
    } catch (e) {
      // Revert
      onLocalUpdate?.({
        sessionId,
        studentName,
        studentEmail,
        recordId,
        source,
        status: previousStatus,
        revert: true,
      });
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to save");
      // Hard fallback - the parent wants a true reload
      onDone?.();
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!recordId) return;
    setSaving(true);
    setOpen(false);
    onLocalUpdate?.({
      sessionId,
      studentName,
      studentEmail,
      recordId,
      source,
      removed: true,
    });
    try {
      await apiClient.delete(`/spotlight/records/${recordId}`);
      toast.success("Removed");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to remove");
      // Reload on failure to re-introduce the row
      onDone?.();
    } finally {
      setSaving(false);
    }
  };

  // Trigger ref + computed menu position. We render the menu through a
  // portal at document.body and position it with `fixed` coords so it
  // escapes any `overflow:hidden` ancestor (e.g. the session-card wrapper
  // that gave the menu its rounded corners). The menu flips above the
  // trigger if there isn't enough room below it.
  const triggerRef = useRef(null);
  const MENU_WIDTH = 200;
  const MENU_HEIGHT_ESTIMATE = 200;
  const [menuStyle, setMenuStyle] = useState({});

  useLayoutEffect(() => {
    if (!open) return;
    const positionMenu = () => {
      const trigger = triggerRef.current;
      if (!trigger) return;
      const rect = trigger.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      const flipAbove = spaceBelow < MENU_HEIGHT_ESTIMATE && rect.top > MENU_HEIGHT_ESTIMATE;
      const top = flipAbove ? rect.top - 4 : rect.bottom + 4;
      // Align the menu's right edge with the trigger's right edge.
      const left = Math.max(8, rect.right - MENU_WIDTH);
      setMenuStyle({
        position: "fixed",
        top,
        left,
        transform: flipAbove ? "translateY(-100%)" : undefined,
        width: MENU_WIDTH,
      });
    };
    positionMenu();
    // If the user scrolls or resizes, just close - simpler than tracking.
    const close = () => setOpen(false);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  return (
    <div className="relative" data-testid={testid}>
      <button
        ref={triggerRef}
        onClick={() => setOpen((v) => !v)}
        disabled={saving}
        className={
          "inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-semibold border transition-colors disabled:opacity-50 " +
          (current
            ? current.chip
            : "bg-white text-[var(--ayci-ink-muted)] border-dashed border-[var(--ayci-border)] hover:border-[var(--ayci-teal)] hover:text-[var(--ayci-teal)]")
        }
        data-testid={`${testid}-button`}
      >
        {saving ? (
          <Loader2 className="w-3 h-3 animate-spin" />
        ) : current ? (
          <>
            <current.icon className={current.value === "spotlighted" ? "w-3 h-3 fill-current" : "w-3 h-3"} />
            {current.label}
          </>
        ) : (
          <>
            <Plus className="w-3 h-3" />
            Mark
          </>
        )}
      </button>
      {open && createPortal(
        <>
          <div className="fixed inset-0 z-[60]" onClick={() => setOpen(false)} />
          <div
            className="z-[70] bg-white rounded-md shadow-lg border border-[var(--ayci-border)] py-1"
            style={menuStyle}
            data-testid={`${testid}-menu`}
          >
            {STATUS_OPTIONS.map((opt) => {
              const OptIcon = opt.icon;
              const active = opt.value === currentStatus;
              return (
                <button
                  key={opt.value}
                  onClick={() => save(opt.value)}
                  data-testid={`${testid}-option-${opt.value}`}
                  className={
                    "flex items-center gap-2 w-full px-3 py-2 text-xs text-left hover:bg-slate-50 " +
                    (active ? "text-[var(--ayci-teal)] font-semibold" : "text-[var(--ayci-ink)]")
                  }
                >
                  {active && <Check className="w-3 h-3" />}
                  <OptIcon className={"w-3 h-3 " + (opt.value === "spotlighted" ? "fill-current" : "")} />
                  {opt.label}
                </button>
              );
            })}
            {allowDelete && recordId && (
              <>
                <div className="border-t border-[var(--ayci-border)] my-1" />
                <button
                  onClick={remove}
                  className="flex items-center gap-2 w-full px-3 py-2 text-xs text-left hover:bg-rose-50 text-rose-700"
                  data-testid={`${testid}-delete`}
                >
                  <Trash2 className="w-3 h-3" />
                  Remove entry
                </button>
              </>
            )}
          </div>
        </>,
        document.body,
      )}
    </div>
  );
}

function ManualAddForm({ session, onClose, onDone }) {
  const [name, setName] = useState("");
  const [status, setStatus] = useState("spotlighted");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      toast.error("Name is required");
      return;
    }
    setSaving(true);
    try {
      await apiClient.post(`/spotlight/records`, {
        session_id: session.id,
        student_name: trimmed,
        status,
        notes,
        source: "manual",
      });
      toast.success(`Added ${trimmed}`);
      onDone?.();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to add");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex items-start gap-2 flex-wrap" data-testid={`spotlight-manual-form-${session.id}`}>
      <input
        type="text"
        placeholder="Student name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="text-sm px-2.5 py-1.5 rounded border border-[var(--ayci-border)] focus:border-[var(--ayci-teal)] focus:outline-none"
        data-testid={`spotlight-manual-name-${session.id}`}
      />
      <select
        value={status}
        onChange={(e) => setStatus(e.target.value)}
        className="text-sm px-2 py-1.5 rounded border border-[var(--ayci-border)] focus:outline-none"
        data-testid={`spotlight-manual-status-${session.id}`}
      >
        {STATUS_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <input
        type="text"
        placeholder="Notes (optional)"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        className="text-sm px-2.5 py-1.5 rounded border border-[var(--ayci-border)] focus:border-[var(--ayci-teal)] focus:outline-none flex-1 min-w-[200px]"
      />
      <Button size="sm" onClick={save} disabled={saving} data-testid={`spotlight-manual-save-${session.id}`}>
        {saving ? <Loader2 className="w-3 h-3 animate-spin mr-2" /> : <Check className="w-3 h-3 mr-2" />}
        Add
      </Button>
      <Button size="sm" variant="ghost" onClick={onClose}>
        <X className="w-3 h-3" />
      </Button>
    </div>
  );
}

// ============================================================================
// HISTORY VIEW
// ============================================================================

function HistoryView() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/spotlight/history", { params: { limit: 40 } });
      setData(data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to load history");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const groups = data?.sessions || [];

  if (loading && !data) {
    return (
      <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-8 text-center text-[var(--ayci-ink-muted)]">
        <Loader2 className="w-6 h-6 animate-spin mx-auto mb-3 text-[var(--ayci-teal)]" />
        Loading history…
      </div>
    );
  }

  if (groups.length === 0) {
    return (
      <div
        className="bg-white border border-[var(--ayci-border)] rounded-lg p-8 text-center text-[var(--ayci-ink-muted)]"
        data-testid="spotlight-history-empty"
      >
        <HistoryIcon className="w-6 h-6 mx-auto mb-3 text-[var(--ayci-ink-muted)]" />
        No spotlight records yet. Mark someone on a session above to start tracking.
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="spotlight-history-list">
      {groups.map((g) => (
        <HistoryGroup key={g.session_id} group={g} onChange={load} />
      ))}
    </div>
  );
}

function HistoryGroup({ group, onChange }) {
  const label = SESSION_LABEL[group.session_type] || "Session";
  const badge = SESSION_BADGE[group.session_type] || "bg-slate-50 text-slate-700 border-slate-200";
  const spotlighted = group.counts?.spotlighted || 0;
  return (
    <section
      className="bg-white border border-[var(--ayci-border)] rounded-lg shadow-sm overflow-hidden"
      data-testid={`spotlight-history-group-${group.session_id}`}
    >
      <div className="px-5 py-3 border-b border-[var(--ayci-border)] bg-slate-50/50 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full border font-semibold ${badge}`}>
              {label}
            </span>
            <span className="text-xs text-[var(--ayci-ink-muted)]">
              {group.session_starts_at ? formatUkDateTime(group.session_starts_at) : "-"}
            </span>
          </div>
          <h3 className="font-display font-semibold text-[var(--ayci-ink)]">{group.session_name || "Unknown session"}</h3>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <CountChip count={spotlighted} total={group.records.length} label="Spotlighted" tone="emerald" />
          {(group.counts?.skipped || 0) > 0 && (
            <CountChip count={group.counts.skipped} label="Skipped" tone="amber" />
          )}
          {(group.counts?.didnt_attend || 0) > 0 && (
            <CountChip count={group.counts.didnt_attend} label="No-show" tone="slate" />
          )}
          {(group.counts?.not_submitted_correctly || 0) > 0 && (
            <CountChip count={group.counts.not_submitted_correctly} label="Bad submission" tone="rose" />
          )}
        </div>
      </div>
      <ul className="divide-y divide-[var(--ayci-border)]">
        {group.records.map((r) => {
          const meta = STATUS_META[r.status] || STATUS_OPTIONS[0];
          const MetaIcon = meta.icon;
          return (
            <li key={r.id} className="px-5 py-3 flex items-center justify-between gap-3 flex-wrap text-sm" data-testid={`spotlight-history-record-${r.id}`}>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-[var(--ayci-ink)]">{r.student_name}</span>
                  <span
                    className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border font-semibold ${meta.chip}`}
                  >
                    <MetaIcon className={"w-3 h-3 " + (r.status === "spotlighted" ? "fill-current" : "")} />
                    {meta.label}
                  </span>
                  {r.source === "manual" && (
                    <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-violet-100 text-violet-800 border border-violet-200 font-semibold">
                      Manual
                    </span>
                  )}
                </div>
                {r.notes && <div className="text-xs text-[var(--ayci-ink-muted)] mt-0.5 italic">{r.notes}</div>}
              </div>
              <div className="text-[10px] text-[var(--ayci-ink-muted)] text-right whitespace-nowrap">
                <div>by {r.recorded_by_name}</div>
                <div>{r.recorded_at ? new Date(r.recorded_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : ""}</div>
              </div>
              <OutcomePicker
                sessionId={group.session_id}
                studentName={r.student_name}
                studentEmail={r.student_email}
                currentStatus={r.status}
                recordId={r.id}
                source={r.source}
                allowDelete
                onDone={onChange}
                testid={`spotlight-history-outcome-${r.id}`}
              />
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function CountChip({ count, total, label, tone }) {
  const toneMap = {
    emerald: "bg-emerald-50 text-emerald-800 border-emerald-200",
    amber: "bg-amber-50 text-amber-800 border-amber-200",
    slate: "bg-slate-50 text-slate-700 border-slate-200",
    rose: "bg-rose-50 text-rose-800 border-rose-200",
  };
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded border tabular-nums ${toneMap[tone] || toneMap.slate}`}>
      {count}
      {total != null ? `/${total}` : ""} {label}
    </span>
  );
}

function Stat({ label, value, tone = "slate", testid }) {
  const toneMap = {
    slate: "bg-white text-[var(--ayci-ink)]",
    rose: "bg-rose-50 text-rose-700 border-rose-200",
  };
  return (
    <div
      className={`text-center px-3 py-2 rounded border border-[var(--ayci-border)] ${toneMap[tone]}`}
      data-testid={testid}
    >
      <div className="font-display font-bold text-2xl tabular-nums leading-none">{value}</div>
      <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] mt-1">{label}</div>
    </div>
  );
}


// Gold/silver/bronze pill for the top-3 leaderboard scorers in a session.
// Anchors the team's intuition that "the top of the table is here because
// they have the most badges". Falls back to a plain count below.
function LeaderboardRankPill({ rank, score }) {
  const ordinal = rank === 1 ? "1st" : rank === 2 ? "2nd" : rank === 3 ? "3rd" : `${rank}th`;
  const tone =
    rank === 1
      ? "bg-amber-100 text-amber-900 border-amber-400"
      : rank === 2
        ? "bg-slate-200 text-slate-800 border-slate-400"
        : rank === 3
          ? "bg-orange-100 text-orange-900 border-orange-400"
          : "bg-slate-100 text-slate-700 border-slate-300";
  const trophy = rank === 1 ? "🏆" : rank === 2 ? "🥈" : rank === 3 ? "🥉" : "";
  return (
    <span
      className={`inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border-2 font-bold uppercase tracking-wider tabular-nums ${tone}`}
      title={`Ranked ${ordinal} on the cohort leaderboard - ${score} Circle badges (cohort & private tier badges excluded). Matches the Leaderboard tab.`}
      data-testid={`leaderboard-rank-${rank}`}
    >
      {trophy && <span aria-hidden>{trophy}</span>}
      Leaderboard #{rank}
      <span className="font-semibold opacity-70">· {score}</span>
    </span>
  );
}

// Small italic reason line under the name explaining why this row is in the
// top 3. Closes the "I can't tell if it's prioritising" loop.
function PriorityReason({ student, index }) {
  const days = student.days_until_interview;
  const interviewSoon = days !== null && days !== undefined && days <= 7;
  let reason;
  if (interviewSoon) {
    reason =
      days === 0
        ? "Interview today"
        : days === 1
          ? "Interview tomorrow"
          : `Interview in ${days} days`;
  } else if (student.cohort_leaderboard_rank && student.cohort_leaderboard_rank <= 3) {
    reason = `Top ${student.cohort_leaderboard_rank === 1 ? "of" : "3 on"} the cohort leaderboard`;
  } else if (student.leaderboard_rank && student.leaderboard_rank <= 3 && (student.leaderboard_score || 0) > 0) {
    // Session-local: they have the most badges among today's submitters
    reason = "Most badges among today's submitters";
  } else if (index === 0) {
    reason = "Earliest eligible submission";
  } else {
    return null;
  }
  return (
    <div
      className="text-[10px] text-amber-700 italic mt-1 font-medium"
      data-testid="priority-reason"
    >
      ↑ Prioritised: {reason}
    </div>
  );
}
