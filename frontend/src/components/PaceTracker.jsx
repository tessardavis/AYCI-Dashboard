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

function ForecastSparkline({
  currentCumul = [],
  prevCumul = [],
  targets = {},
  forecast = 0,
  todayOffset = 0,
  barColor = "#0ea5e9",
  width = 110,
  height = 44,
}) {
  // Build x range from min day_offset to max day_offset across all series
  const allOffsets = [
    ...currentCumul.map((p) => p.day_offset),
    ...prevCumul.flatMap((s) => s.series?.map((p) => p.day_offset) || []),
  ];
  const allValues = [
    ...currentCumul.map((p) => p.value),
    ...prevCumul.flatMap((s) => s.series?.map((p) => p.value) || []),
    targets.good || 0,
    targets.better || 0,
    targets.best || 0,
    forecast || 0,
  ];
  if (allOffsets.length === 0 || allValues.length === 0) {
    return <div className="w-[110px] h-[44px]" />;
  }
  const xMin = Math.min(...allOffsets, 0);
  const xMax = Math.max(...allOffsets, todayOffset);
  const yMax = Math.max(...allValues, 1);
  const xRange = Math.max(xMax - xMin, 1);
  const px = (x) => ((x - xMin) / xRange) * (width - 2) + 1;
  const py = (y) => height - 2 - (y / yMax) * (height - 4);
  const toPath = (series) =>
    series.length === 0
      ? ""
      : series
          .map((p, i) => `${i === 0 ? "M" : "L"} ${px(p.day_offset)} ${py(p.value)}`)
          .join(" ");

  // forecast endpoint at last day_offset of current launch (or today)
  const lastCurrent = currentCumul[currentCumul.length - 1];
  const forecastX = px(xMax);
  const forecastY = py(forecast);
  const todayPoint = lastCurrent
    ? { x: px(lastCurrent.day_offset), y: py(lastCurrent.value) }
    : null;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="overflow-visible flex-shrink-0"
      data-testid="pace-forecast-sparkline"
    >
      {/* Target reference line (best) */}
      {targets.best > 0 && (
        <line
          x1={1}
          x2={width - 1}
          y1={py(targets.best)}
          y2={py(targets.best)}
          stroke="#7c3aed"
          strokeWidth="1"
          strokeDasharray="2 2"
          opacity="0.4"
        />
      )}
      {/* Previous launch curves (faded) */}
      {prevCumul.map((s, i) => (
        <path
          key={s.id || i}
          d={toPath(s.series || [])}
          fill="none"
          stroke="#94a3b8"
          strokeWidth="1"
          opacity="0.5"
        />
      ))}
      {/* Current launch curve */}
      <path
        d={toPath(currentCumul)}
        fill="none"
        stroke={barColor}
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Forecast projection (dashed line from today → forecast) */}
      {todayPoint && (
        <line
          x1={todayPoint.x}
          y1={todayPoint.y}
          x2={forecastX}
          y2={forecastY}
          stroke={barColor}
          strokeWidth="1.25"
          strokeDasharray="2 2"
          opacity="0.7"
        />
      )}
      {/* Today dot */}
      {todayPoint && (
        <circle cx={todayPoint.x} cy={todayPoint.y} r="2" fill={barColor} />
      )}
      {/* Forecast dot */}
      <circle
        cx={forecastX}
        cy={forecastY}
        r="2.5"
        fill="white"
        stroke={barColor}
        strokeWidth="1.5"
      />
    </svg>
  );
}

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
          <div className="flex items-end justify-between gap-2">
            <div>
              <div className="font-display font-bold text-2xl text-[var(--ayci-ink)]">
                {fmtGbp(pace.forecast)}
              </div>
              <div className={`inline-block text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full ${tone.bg} ${tone.text} font-semibold mt-1`}>
                {pace.verdict}
              </div>
            </div>
            <ForecastSparkline
              currentCumul={pace.current_cumul}
              prevCumul={pace.prev_cumul}
              targets={targets}
              forecast={pace.forecast}
              todayOffset={pace.today_offset}
              barColor={tone.bar}
            />
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
