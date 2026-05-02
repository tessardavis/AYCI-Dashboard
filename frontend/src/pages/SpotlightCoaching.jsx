import { useEffect, useState } from "react";
import { Calendar, Loader2, RefreshCw, ExternalLink, AlertCircle, Clock, Users, Award, Send } from "lucide-react";
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

function formatUkDateTime(iso) {
  if (!iso) return "—";
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

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

export default function SpotlightCoaching() {
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

  const sessions = data?.sessions || [];

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="spotlight-page">
      <HeroBanner
        {...(HERO_PRESETS.spotlight || HERO_PRESETS.cohort)}
        eyebrow="Coach prep"
        title="Spotlight Coaching"
        subtitle="The next live sessions, the people who've put themselves forward, and who has an interview coming up."
        testid="spotlight-hero"
        actions={
          <Button
            variant="outline"
            onClick={load}
            disabled={loading}
            data-testid="spotlight-refresh"
            className="bg-white/95 border-white/20 text-[var(--ayci-ink)] hover:bg-white"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4 mr-2" />
            )}
            Refresh
          </Button>
        }
      />

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
        <SessionCard key={`${s.id}-${idx}`} session={s} primary={idx === 0} />
      ))}
    </div>
  );
}

function SessionCard({ session, primary }) {
  const label = SESSION_LABEL[session.session_type] || "Session";
  const badge = SESSION_BADGE[session.session_type] || "bg-slate-50 text-slate-700 border-slate-200";
  const [sending, setSending] = useState(false);

  const sendSlackPreview = async () => {
    setSending(true);
    try {
      const { data } = await apiClient.post(`/spotlight/slack/test`, null, {
        params: { session_id: session.id },
        timeout: 30000,
      });
      if (data.sent) {
        toast.success("Slack preview sent — check your channel");
      } else {
        toast.error(
          data.reason || data.error || "Slack send failed — is SLACK_WEBHOOK_URL set?"
        );
      }
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to send");
    } finally {
      setSending(false);
    }
  };

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
            <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)] leading-tight">
              {session.name}
            </h2>
            <div className="flex items-center gap-3 mt-1.5 text-xs text-[var(--ayci-ink-muted)] flex-wrap">
              <span className="inline-flex items-center gap-1.5">
                <Calendar className="w-3.5 h-3.5" />
                {formatUkDateTime(session.starts_at)} (UK)
              </span>
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
          <div className="flex items-center gap-3 shrink-0">
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
              {sending ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Send className="w-3 h-3" />
              )}
              {sending ? "Sending…" : "Slack preview"}
            </button>
          </div>
        </div>
      </div>

      {session.students.length === 0 ? (
        <div
          className="p-6 text-center text-sm text-[var(--ayci-ink-muted)]"
          data-testid={`spotlight-students-empty-${session.id}`}
        >
          <Users className="w-5 h-5 mx-auto mb-2 text-[var(--ayci-ink-muted)]" />
          No spotlight submissions yet for this session.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] border-b border-[var(--ayci-border)]">
                <th className="px-4 py-2 font-semibold w-[1%] whitespace-nowrap">Priority</th>
                <th className="px-4 py-2 font-semibold">Student</th>
                <th className="px-4 py-2 font-semibold">Topic they'd like to work on</th>
                <th className="px-3 py-2 font-semibold whitespace-nowrap">Interview</th>
                <th className="px-3 py-2 font-semibold whitespace-nowrap">Submitted</th>
              </tr>
            </thead>
            <tbody>
              {session.students.map((st, i) => (
                <StudentRow key={`${st.name}-${st.submitted_at}-${i}`} student={st} index={i} session={session} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function StudentRow({ student, index, session }) {
  const days = student.days_until_interview;
  const interviewSoon = days !== null && days !== undefined && days <= 7;
  const rowClass = interviewSoon
    ? "bg-rose-50/40 hover:bg-rose-50/70"
    : "hover:bg-slate-50/50";
  return (
    <tr
      className={`border-b border-[var(--ayci-border)] last:border-b-0 ${rowClass}`}
      data-testid={`spotlight-row-${session.id}-${index}`}
    >
      <td className="px-4 py-3 whitespace-nowrap">
        <div
          className={
            "inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold " +
            (interviewSoon
              ? "bg-rose-600 text-white"
              : "bg-slate-100 text-[var(--ayci-ink)]")
          }
        >
          {index + 1}
        </div>
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-[var(--ayci-ink)]">{student.name}</span>
          {student.leaderboard_score != null && student.leaderboard_score > 0 && (
            <span
              className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200 font-semibold tabular-nums"
              title="Number of Circle badges (cohort + private tier badges excluded)"
              data-testid={`spotlight-badges-${session.id}-${index}`}
            >
              <Award className="w-3 h-3" />
              {student.leaderboard_score}
            </span>
          )}
        </div>
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
            title={`Submitted ${student.submitted_uk_date} — needs to be the day before (${session.deadline_uk_date})`}
          >
            <AlertCircle className="w-3 h-3" /> Early
          </span>
        )}
      </td>
      <td className="px-4 py-3 text-[var(--ayci-ink)] max-w-[440px]">
        <div className="whitespace-pre-wrap break-words">{student.topic || <span className="text-[var(--ayci-ink-muted)] italic">(no topic given)</span>}</div>
      </td>
      <td className="px-3 py-3 whitespace-nowrap">
        {student.interview_date ? (
          <div>
            <div
              className={
                "font-semibold tabular-nums " +
                (interviewSoon ? "text-rose-700" : "text-[var(--ayci-ink)]")
              }
            >
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
          <span className="text-xs text-[var(--ayci-ink-muted)]">—</span>
        )}
      </td>
      <td className="px-3 py-3 text-xs text-[var(--ayci-ink-muted)] whitespace-nowrap tabular-nums">
        {formatDate(student.submitted_uk_date)}
      </td>
    </tr>
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
      <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] mt-1">
        {label}
      </div>
    </div>
  );
}
