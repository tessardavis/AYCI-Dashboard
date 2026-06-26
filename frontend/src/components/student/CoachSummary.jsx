import { Phone, Video, Award, Briefcase, Calendar, CheckCircle2 } from "lucide-react";

const fmtDate = (iso) => {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  } catch {
    return iso;
  }
};

const fmtShort = (iso) => {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
    });
  } catch {
    return iso;
  }
};

export default function CoachSummary({ result }) {
  const monday = result?.monday?.data || {};
  const allowances = monday.allowances || {};
  const tier = monday?.columns?.Tier?.text || "-";
  const calls = allowances.calls_30min;
  const mocks = allowances.mock_interviews;
  const bonus = allowances.bonus_calls;
  const videos = allowances.videos;

  const calendly = result?.calendly?.data || {};
  const upcomingCalls = calendly?.upcoming || [];
  const pastCalls = calendly?.past || [];
  const lastCall = pastCalls[0];
  const nextCall = upcomingCalls[0];
  const tallyType = result?.tally?.type;
  const tallyCount = result?.tally?.history_count || 0;

  const totalCallsRemaining =
    (calls?.available || 0) + (mocks?.available || 0) + (bonus?.available || 0);
  const totalCallsUsed =
    (calls?.used || 0) + (mocks?.used || 0) + (bonus?.used || 0);
  const totalCallsBooked = upcomingCalls.length + pastCalls.length;

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
      data-testid="coach-summary"
    >
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <span className="text-[10px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)]">
          Coach view
        </span>
        <span
          className="px-2 py-0.5 bg-violet-50 text-violet-700 border border-violet-200 rounded-full text-[10px] uppercase tracking-wider font-semibold"
          data-testid="coach-summary-tier"
        >
          {tier}
        </span>
        {tallyType && (
          <span
            className={`inline-flex items-center gap-1 px-2 py-0.5 border rounded-full text-[10px] uppercase tracking-wider font-semibold ${
              tallyType.toLowerCase().includes("locum")
                ? "bg-amber-50 text-amber-700 border-amber-200"
                : "bg-sky-50 text-sky-700 border-sky-200"
            }`}
            title="Latest interview type from Tally"
          >
            <Briefcase className="w-3 h-3" />
            {tallyType}
          </span>
        )}
        {tallyCount > 0 && (
          <span className="text-[10px] text-[var(--ayci-ink-muted)]">
            · {tallyCount} prior interview{tallyCount > 1 ? "s" : ""}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <CallsStat
          callsRemaining={totalCallsRemaining}
          callsUsed={totalCallsUsed}
          callsTotal={(calls?.total || 0) + (mocks?.total || 0) + (bonus?.total || 0)}
          nextCall={nextCall}
          upcomingCount={upcomingCalls.length}
          pastCount={pastCalls.length}
          totalBooked={totalCallsBooked}
        />
        <SummaryStat
          icon={Video}
          label="Videos remaining"
          value={videos?.remaining ?? "-"}
          sub={
            videos?.allowance
              ? `${videos.submitted}/${videos.allowance} submitted`
              : "Not in tier"
          }
          tone="violet"
          testid="summary-videos"
        />
        <SummaryStat
          icon={Award}
          label="Mocks left"
          value={mocks?.available ?? 0}
          sub={`${mocks?.used || 0} used · ${mocks?.total || 0} eligible`}
          tone="rose"
          testid="summary-mocks"
        />
        <SummaryStat
          icon={Calendar}
          label="Last call"
          value={lastCall ? fmtShort(lastCall.start_time) : "-"}
          sub={lastCall ? lastCall.name : "No Calendly history"}
          tone="amber"
          testid="summary-last-call"
        />
      </div>
    </div>
  );
}

function CallsStat({
  callsRemaining,
  callsUsed,
  callsTotal,
  nextCall,
  upcomingCount,
  pastCount,
  totalBooked,
}) {
  return (
    <div
      className="border rounded-lg p-3 bg-emerald-50 border-emerald-200 flex flex-col"
      data-testid="summary-calls"
    >
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)]">
        <Phone className="w-3 h-3" />
        Calls
      </div>
      {nextCall ? (
        <>
          <div className="flex items-baseline gap-1.5 mt-1">
            <span className="font-display font-bold text-lg text-emerald-800 leading-tight">
              {fmtShort(nextCall.start_time)}
            </span>
            <span className="inline-flex items-center gap-0.5 text-[10px] font-bold text-emerald-700 bg-white border border-emerald-300 px-1.5 py-0.5 rounded-full">
              <CheckCircle2 className="w-3 h-3" />
              Next
            </span>
          </div>
          <div className="text-[10px] text-[var(--ayci-ink-muted)] mt-0.5 truncate" title={nextCall.name}>
            {nextCall.name}
          </div>
          <div className="text-[10px] text-[var(--ayci-ink-muted)] mt-1.5 pt-1.5 border-t border-emerald-200/60">
            <span className="font-semibold text-emerald-800">{callsRemaining} left</span> ·{" "}
            {callsUsed}/{callsTotal} used
            {upcomingCount > 1 && <span> · {upcomingCount} upcoming</span>}
          </div>
        </>
      ) : totalBooked > 0 ? (
        <>
          <div className="font-display font-bold text-2xl text-[var(--ayci-ink)] mt-1 leading-tight">
            {callsRemaining}
          </div>
          <div className="text-[10px] text-[var(--ayci-ink-muted)] mt-0.5">
            <span className="font-semibold text-emerald-800">remaining</span> · {callsUsed}/{callsTotal} used
          </div>
          <div className="text-[10px] text-amber-700 mt-1.5 pt-1.5 border-t border-emerald-200/60 font-semibold">
            ⚠ No upcoming call booked
          </div>
        </>
      ) : (
        <>
          <div className="font-display font-bold text-2xl text-[var(--ayci-ink)] mt-1 leading-tight">
            {callsRemaining}
          </div>
          <div className="text-[10px] text-[var(--ayci-ink-muted)] mt-0.5">
            remaining · {callsTotal} total
          </div>
          {callsTotal > 0 && (
            <div className="text-[10px] text-amber-700 mt-1.5 pt-1.5 border-t border-emerald-200/60 font-semibold">
              ⚠ Hasn't booked any call yet
            </div>
          )}
        </>
      )}
    </div>
  );
}

function SummaryStat({ icon: Icon, label, value, sub, tone, testid }) {
  const TONES = {
    teal: "bg-emerald-50 border-emerald-200",
    rose: "bg-rose-50 border-rose-200",
    violet: "bg-violet-50 border-violet-200",
    amber: "bg-amber-50 border-amber-200",
  };
  return (
    <div
      className={`border rounded-lg p-3 ${TONES[tone] || TONES.teal}`}
      data-testid={testid}
    >
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)]">
        <Icon className="w-3 h-3" />
        {label}
      </div>
      <div className="font-display font-bold text-2xl text-[var(--ayci-ink)] mt-1 leading-tight">
        {value}
      </div>
      {sub && (
        <div className="text-[10px] text-[var(--ayci-ink-muted)] mt-0.5 line-clamp-2">
          {sub}
        </div>
      )}
    </div>
  );
}
