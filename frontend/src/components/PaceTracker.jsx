import { useEffect, useState } from "react";
import { TrendingUp, Loader2, Target, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";

const fmtGbp = (v) =>
  `£${Number(v || 0).toLocaleString("en-GB", { maximumFractionDigits: 0 })}`;

const VERDICT_TONE = {
  "On pace for Best": { bg: "bg-violet-50", text: "text-violet-700", bar: "#7c3aed" },
  "On pace for Better": { bg: "bg-amber-50", text: "text-amber-700", bar: "#f59e0b" },
  "On pace for Good": { bg: "bg-emerald-50", text: "text-emerald-700", bar: "#10b981" },
  "Below Good": { bg: "bg-rose-50", text: "text-rose-700", bar: "#ef4444" },
};

export default function PaceTrackerWidget() {
  const [pace, setPace] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient
      .get("/launches/active/pace", { timeout: 90000 })
      .then((r) => setPace(r.data))
      .catch(() => setPace(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-4 shadow-sm flex items-center gap-2 text-xs text-[var(--ayci-ink-muted)] min-h-[120px]">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading pace forecast…
      </div>
    );
  }

  if (!pace || pace.active === false) {
    return null;
  }

  const tone = VERDICT_TONE[pace.verdict] || VERDICT_TONE["Below Good"];
  const targets = pace.targets || {};
  const max = Math.max(targets.best || 0, pace.forecast || 0, 1);
  const pct = (val) => `${Math.min(100, (val / max) * 100)}%`;

  return (
    <Link
      to="/launches"
      className="block bg-white border border-[var(--ayci-border)] rounded-lg p-4 shadow-sm hover:shadow-md transition-shadow group"
      data-testid="pace-tracker-widget"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${tone.bg}`}>
            <TrendingUp className={`w-4 h-4 ${tone.text}`} />
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">
              {pace.launch_name} pace
            </div>
            <div className="text-[10px] text-[var(--ayci-ink-muted)]">
              Day {pace.today_offset} · {pace.days_to_close} to close
            </div>
          </div>
        </div>
        <ChevronRight className="w-4 h-4 text-[var(--ayci-ink-muted)] group-hover:text-[var(--ayci-teal)] transition-colors" />
      </div>

      {pace.forecast !== null ? (
        <>
          <div className="font-display font-bold text-2xl text-[var(--ayci-ink)]">
            {fmtGbp(pace.forecast)}
          </div>
          <div className={`inline-block text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full ${tone.bg} ${tone.text} font-semibold mt-1`}>
            {pace.verdict}
          </div>
          <div className="mt-3 relative h-2 bg-slate-100 rounded-full">
            {/* Target markers */}
            {[
              { label: "G", value: targets.good, color: "#10b981" },
              { label: "B", value: targets.better, color: "#f59e0b" },
              { label: "★", value: targets.best, color: "#7c3aed" },
            ].map((t) => (
              <div
                key={t.label}
                className="absolute top-0 bottom-0 w-px"
                style={{ left: pct(t.value), backgroundColor: t.color }}
              >
                <span
                  className="absolute -top-3.5 -translate-x-1/2 text-[8px] font-bold"
                  style={{ color: t.color }}
                >
                  {t.label}
                </span>
              </div>
            ))}
            {/* Forecast bar */}
            <div
              className="h-full rounded-full transition-all"
              style={{ width: pct(pace.forecast), backgroundColor: tone.bar, opacity: 0.7 }}
            />
            {/* Today marker */}
            <div
              className="absolute top-0 bottom-0 w-1 bg-slate-700 rounded-full"
              style={{ left: pct(pace.today_amount) }}
              title={`Today: ${fmtGbp(pace.today_amount)}`}
            />
          </div>
          <div className="flex justify-between text-[10px] text-[var(--ayci-ink-muted)] mt-1">
            <span>Now: {fmtGbp(pace.today_amount)}</span>
            <span className="capitalize">{pace.confidence} confidence</span>
          </div>
        </>
      ) : (
        <div className="text-xs text-[var(--ayci-ink-muted)] italic">
          {pace.explanation || "Forecast not available yet."}
        </div>
      )}
    </Link>
  );
}

export function PaceTrackerCard() {
  const [pace, setPace] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient
      .get("/launches/active/pace", { timeout: 90000 })
      .then((r) => setPace(r.data))
      .catch(() => setPace(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--ayci-teal)] inline mr-2" />
        <span className="text-sm text-[var(--ayci-ink-muted)]">Computing pace forecast…</span>
      </div>
    );
  }

  if (!pace || pace.active === false || pace.forecast === null) {
    return null;
  }

  const tone = VERDICT_TONE[pace.verdict] || VERDICT_TONE["Below Good"];

  return (
    <section
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
      data-testid="pace-tracker-card"
    >
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="font-display font-bold text-lg text-[var(--ayci-ink)]">
            <Target className="w-5 h-5 inline mr-2 text-[var(--ayci-teal)]" />
            Pace forecast
          </h2>
          <div className="text-xs text-[var(--ayci-ink-muted)]">
            Based on the {pace.ratios?.length || 0} most recent prior launches
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">Today</div>
          <div className="font-display font-bold text-2xl text-[var(--ayci-ink)]">
            {fmtGbp(pace.today_amount)}
          </div>
          <div className="text-[11px] text-[var(--ayci-ink-muted)]">Day {pace.today_offset}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">Forecast</div>
          <div className={`font-display font-bold text-2xl ${tone.text}`}>
            {fmtGbp(pace.forecast)}
          </div>
          <div className="text-[11px] text-[var(--ayci-ink-muted)] capitalize">
            {pace.confidence} confidence
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">Avg ratio</div>
          <div className="font-display font-bold text-2xl text-[var(--ayci-ink)]">
            {pace.avg_ratio}×
          </div>
          <div className="text-[11px] text-[var(--ayci-ink-muted)]">final / today</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">Verdict</div>
          <div className={`inline-block text-xs uppercase tracking-wider px-2 py-1 rounded-full ${tone.bg} ${tone.text} font-semibold mt-2`}>
            {pace.verdict}
          </div>
        </div>
      </div>

      {pace.ratios?.length > 0 && (
        <div className="border-t border-[var(--ayci-border)] pt-3">
          <div className="text-xs text-[var(--ayci-ink-muted)] mb-2">
            How prior launches grew from day {pace.today_offset} to close:
          </div>
          <div className="space-y-1.5">
            {pace.ratios.map((r) => (
              <div key={r.id} className="flex items-center justify-between text-sm bg-slate-50 rounded p-2 border border-[var(--ayci-border)]">
                <span className="font-medium text-[var(--ayci-ink)]">{r.name}</span>
                <span className="text-[var(--ayci-ink-muted)] text-xs">
                  {fmtGbp(r.amount_at_today)} → {fmtGbp(r.final)} <strong className="text-[var(--ayci-ink)]">({r.ratio}×)</strong>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
