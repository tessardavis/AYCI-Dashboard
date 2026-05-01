import { useEffect, useState } from "react";
import { Activity, Target, Flag, Bell, Users, Loader2 } from "lucide-react";
import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";

const PILLAR_META = {
  scorecard: { icon: Target, label: "Scorecard goals" },
  rocks: { icon: Flag, label: "Quarterly rocks" },
  sla: { icon: Bell, label: "SLA breaches" },
  students: { icon: Users, label: "At-risk students" },
};

const PILLAR_ORDER = ["scorecard", "rocks", "sla", "students"];

function tierFor(score) {
  if (score >= 80) return { tone: "emerald", text: "Healthy", grad: "from-emerald-500 to-teal-500" };
  if (score >= 60) return { tone: "amber", text: "Watch", grad: "from-amber-500 to-orange-500" };
  return { tone: "rose", text: "At risk", grad: "from-rose-500 to-pink-500" };
}

const TONE_TEXT = {
  emerald: "text-emerald-700",
  amber: "text-amber-700",
  rose: "text-rose-700",
};
const TONE_BG = {
  emerald: "bg-emerald-50 border-emerald-200",
  amber: "bg-amber-50 border-amber-200",
  rose: "bg-rose-50 border-rose-200",
};

export default function PulseCard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await apiClient.get("/pulse-score", { timeout: 30000 });
        if (!cancelled) setData(data);
      } catch (e) {
        if (!cancelled)
          toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to load Pulse Score");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div
        className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 mb-5 shadow-sm flex items-center gap-3 text-sm text-[var(--ayci-ink-muted)]"
        data-testid="pulse-card-loading"
      >
        <Loader2 className="w-4 h-4 animate-spin text-[var(--ayci-accent)]" />
        Computing Pulse Score…
      </div>
    );
  }

  if (!data) return null;

  const tier = tierFor(data.score);
  const r = 36;
  const c = 2 * Math.PI * r;
  const offset = c - (data.score / 100) * c;

  return (
    <div
      className={`border rounded-lg p-5 mb-5 shadow-sm ${TONE_BG[tier.tone]}`}
      data-testid="pulse-card"
    >
      <div className="flex flex-col lg:flex-row gap-5 lg:items-stretch">
        {/* Score ring + label */}
        <div className="flex items-center gap-5 lg:pr-6 lg:border-r lg:border-[var(--ayci-border)]">
          <div className="relative w-[96px] h-[96px] shrink-0" data-testid="pulse-ring">
            <svg width="96" height="96" className="-rotate-90">
              <circle cx="48" cy="48" r={r} stroke="rgba(0,0,0,0.08)" strokeWidth="8" fill="none" />
              <defs>
                <linearGradient id={`pulse-grad-${tier.tone}`} x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor={tier.tone === "emerald" ? "#10b981" : tier.tone === "amber" ? "#f59e0b" : "#f43f5e"} />
                  <stop offset="100%" stopColor={tier.tone === "emerald" ? "#14b8a6" : tier.tone === "amber" ? "#f97316" : "#ec4899"} />
                </linearGradient>
              </defs>
              <circle
                cx="48"
                cy="48"
                r={r}
                stroke={`url(#pulse-grad-${tier.tone})`}
                strokeWidth="8"
                fill="none"
                strokeDasharray={c}
                strokeDashoffset={offset}
                strokeLinecap="round"
                style={{ transition: "stroke-dashoffset 800ms ease-out" }}
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="font-display font-bold text-2xl tabular-nums text-[var(--ayci-ink)]">
                {data.score}
              </span>
              <span className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">
                / 100
              </span>
            </div>
          </div>
          <div className="leading-tight">
            <div
              className={`inline-flex items-center gap-1.5 text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full ${TONE_TEXT[tier.tone]} bg-white/70 border ${TONE_BG[tier.tone].split(" ")[1]}`}
              data-testid="pulse-tier"
            >
              <Activity className="w-3 h-3" />
              {tier.text}
            </div>
            <div className="font-display font-bold text-2xl text-[var(--ayci-ink)] mt-1.5">
              Team Pulse
            </div>
            <div className="text-xs text-[var(--ayci-ink-muted)] mt-0.5">
              Week of {data.week_start}
            </div>
          </div>
        </div>

        {/* Pillars grid */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 flex-1">
          {PILLAR_ORDER.map((key) => (
            <Pillar key={key} pillarKey={key} data={data.pillars[key]} />
          ))}
        </div>
      </div>
    </div>
  );
}

function Pillar({ pillarKey, data }) {
  const meta = PILLAR_META[pillarKey];
  const Icon = meta.icon;
  const pct = data.max > 0 ? Math.round((data.score / data.max) * 100) : 0;
  const barColor = pct >= 80 ? "#10b981" : pct >= 50 ? "#f59e0b" : "#f43f5e";
  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded p-3 flex flex-col"
      data-testid={`pulse-pillar-${pillarKey}`}
    >
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">
        <Icon className="w-3 h-3" />
        {meta.label}
      </div>
      <div className="font-display font-bold text-xl text-[var(--ayci-ink)] mt-1 tabular-nums">
        {data.score}
        <span className="text-sm text-[var(--ayci-ink-muted)] font-normal"> / {data.max}</span>
      </div>
      <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden mt-2">
        <div
          className="h-full rounded-full"
          style={{
            width: `${pct}%`,
            backgroundColor: barColor,
            transition: "width 600ms ease-out",
          }}
        />
      </div>
      <div className="text-[11px] text-[var(--ayci-ink-muted)] mt-1.5 leading-snug">
        {data.label}
      </div>
    </div>
  );
}
