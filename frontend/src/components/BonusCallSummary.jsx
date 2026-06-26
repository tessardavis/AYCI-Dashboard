import { useState, useEffect } from "react";
import { Gift } from "lucide-react";

import { apiClient } from "@/lib/api";

// Live "this cohort" bonus-call snapshot: eligible count + booking-status
// breakdown. Used on the Processes board and the Cohort Dashboard. Hides itself
// if the fetch fails (e.g. the assistant/endpoint isn't reachable).
export default function BonusCallSummary({ className = "" }) {
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
    <div className={"rounded-lg border border-[var(--ayci-border)] bg-white p-4 " + className} data-testid="bonus-summary">
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)] mb-2">
        <Gift className="w-3.5 h-3.5" /> Bonus calls - this cohort
      </div>
      <div className="flex flex-wrap gap-2 items-center">
        {data.eligible != null && (
          <span className="text-sm mr-1">
            <strong className="text-lg text-[var(--ayci-ink)]">{data.eligible}</strong> eligible
          </span>
        )}
        {chips.map(([k, n]) => (
          <span key={k} className="text-xs px-2 py-1 rounded-full bg-slate-50 border border-[var(--ayci-border)]">
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
