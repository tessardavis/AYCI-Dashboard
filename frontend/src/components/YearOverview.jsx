import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { apiClient } from "@/lib/api";

const fmtGbp = (v) =>
  v >= 1000 ? `£${(v / 1000).toFixed(0)}k` : `£${Math.round(v)}`;
const fmtMonth = (iso) =>
  iso ? new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", { month: "short", year: "2-digit", timeZone: "UTC" }) : "";

export default function YearOverview({ onSelect, selectedId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient
      .get("/launches/year-overview", { timeout: 90000 })
      .then((r) => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  // Compute time range - pad a bit on either side
  const range = useMemo(() => {
    if (!data?.launches?.length) return null;
    const dates = [];
    data.launches.forEach((L) => {
      if (L.start_date) dates.push(new Date(L.start_date + "T00:00:00Z"));
      if (L.end_date) dates.push(new Date(L.end_date + "T00:00:00Z"));
    });
    if (data.today) dates.push(new Date(data.today + "T00:00:00Z"));
    const min = new Date(Math.min(...dates));
    const max = new Date(Math.max(...dates));
    // Pad ±10% of total span
    const span = max - min;
    return {
      min: new Date(min.getTime() - span * 0.05),
      max: new Date(max.getTime() + span * 0.05),
    };
  }, [data]);

  if (loading) {
    return (
      <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-4 text-sm text-[var(--ayci-ink-muted)] flex items-center gap-2">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading year overview…
      </div>
    );
  }

  if (!data || !data.launches?.length || !range) return null;

  const totalSpan = range.max - range.min;
  const pct = (date) => `${((new Date(date + "T00:00:00Z") - range.min) / totalSpan) * 100}%`;
  const pctRange = (start, end) => {
    const s = (new Date(start + "T00:00:00Z") - range.min) / totalSpan;
    const e = (new Date(end + "T00:00:00Z") - range.min) / totalSpan;
    return { left: `${s * 100}%`, width: `${(e - s) * 100}%` };
  };

  // Generate month tick labels
  const monthTicks = [];
  const cur = new Date(range.min);
  cur.setUTCDate(1);
  while (cur <= range.max) {
    monthTicks.push(new Date(cur));
    cur.setUTCMonth(cur.getUTCMonth() + 1);
  }

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm"
      data-testid="year-overview"
    >
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-display font-bold text-base text-[var(--ayci-ink)]">
          Year overview
        </h2>
        <div className="text-xs text-[var(--ayci-ink-muted)]">
          Click a launch to switch view · {data.launches.length} launches tracked
        </div>
      </div>

      <div className="relative h-28">
        {/* Month tick labels */}
        <div className="absolute inset-x-0 top-0 h-4 text-[10px] text-[var(--ayci-ink-muted)] pointer-events-none">
          {monthTicks.map((m) => (
            <div
              key={m.toISOString()}
              className="absolute -translate-x-1/2"
              style={{ left: pct(m.toISOString().split("T")[0]) }}
            >
              {m.getUTCMonth() === 0 ? `${m.getUTCFullYear()}` : fmtMonth(m.toISOString().split("T")[0])}
            </div>
          ))}
        </div>

        {/* Launch bars */}
        <div className="absolute inset-x-0 top-6 bottom-2">
          {data.launches.map((L, idx) => {
            const { left, width } = pctRange(L.start_date, L.end_date);
            const isSelected = L.id === selectedId;
            const tone = L.is_active
              ? { bg: "#4457B6", border: "#182E87" }
              : L.is_future
              ? { bg: "#e2e8f0", border: "#cbd5e1" }
              : { bg: "#94a3b8", border: "#64748b" };
            return (
              <button
                key={L.id}
                onClick={() => onSelect && onSelect(L.id)}
                style={{
                  left,
                  width,
                  top: `${(idx % 2) * 30 + 8}px`,
                  backgroundColor: tone.bg,
                  borderColor: isSelected ? "#182E87" : tone.border,
                  borderWidth: isSelected ? 2 : 1,
                  boxShadow: isSelected ? "0 0 0 3px rgba(14, 165, 233, 0.25)" : "none",
                }}
                className="absolute h-7 rounded-md flex items-center justify-center px-2 text-[11px] font-semibold text-white hover:brightness-105 transition-all overflow-hidden whitespace-nowrap"
                data-testid={`year-overview-launch-${L.code || L.id}`}
                title={`${L.name} · ${fmtGbp(L.revenue_gbp)} · ${L.sales_count} sales`}
              >
                {L.code || L.name}{L.revenue_gbp > 0 && (
                  <span className="ml-1.5 opacity-90 font-normal">{fmtGbp(L.revenue_gbp)}</span>
                )}
              </button>
            );
          })}
        </div>

        {/* Today marker */}
        {data.today && (
          <div
            className="absolute top-5 bottom-0 w-0.5 bg-rose-500 z-10 pointer-events-none"
            style={{ left: pct(data.today) }}
          >
            <div className="absolute -top-1 -left-1 w-2 h-2 rounded-full bg-rose-500" />
            <div className="absolute -bottom-5 -translate-x-1/2 text-[9px] uppercase tracking-wider font-bold text-rose-600">
              Today
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
