import { useState, useEffect } from "react";
import { Phone } from "lucide-react";

import { apiClient } from "@/lib/api";

// Live roll-up of private-tier (Private Plus / VIP) call bookings: total active
// calls + breakdowns by call type and coach. Shown on the Private Tier calls
// process. Hides itself if the fetch fails or there's nothing booked yet.
export default function PrivateCallSummary({ className = "" }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    apiClient.get("/private-call/summary").then(({ data }) => setData(data)).catch(() => {});
  }, []);

  if (!data) return null;
  const labels = data.kind_labels || {};
  const byKind = Object.entries(data.by_kind || {}).filter(([k]) => k !== "?");
  const byCoach = Object.entries(data.by_coach || {}).filter(([c]) => c !== "?");
  const noShows = data.by_status?.["No-show"] || 0;

  return (
    <div className={"rounded-lg border border-[var(--ayci-border)] bg-white p-4 " + className} data-testid="private-call-summary">
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)] mb-2">
        <Phone className="w-3.5 h-3.5" /> Private Tier calls - booked to date
      </div>
      <div className="flex flex-wrap gap-2 items-center mb-2">
        <span className="text-sm mr-1">
          <strong className="text-lg text-[var(--ayci-ink)]">{data.active_calls ?? 0}</strong> calls booked
        </span>
        <span className="text-sm mr-1">
          <strong className="text-lg text-[var(--ayci-ink)]">{data.students_with_calls ?? 0}</strong> students
        </span>
        {noShows > 0 && (
          <span className="text-xs px-2 py-1 rounded-full bg-rose-50 border border-rose-200 text-rose-700">
            No-show: <strong>{noShows}</strong>
          </span>
        )}
      </div>
      {data.active_calls === 0 ? (
        <span className="text-xs text-[var(--ayci-ink-muted)]">No private-tier calls booked yet.</span>
      ) : (
        <div className="space-y-1.5">
          {byKind.length > 0 && (
            <div className="flex flex-wrap gap-2 items-center">
              <span className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] w-16">By type</span>
              {byKind.map(([k, n]) => (
                <span key={k} className="text-xs px-2 py-1 rounded-full bg-slate-50 border border-[var(--ayci-border)]">
                  {labels[k] || k}: <strong>{n}</strong>
                </span>
              ))}
            </div>
          )}
          {byCoach.length > 0 && (
            <div className="flex flex-wrap gap-2 items-center">
              <span className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] w-16">By coach</span>
              {byCoach.map(([c, n]) => (
                <span key={c} className="text-xs px-2 py-1 rounded-full bg-slate-50 border border-[var(--ayci-border)]">
                  {c}: <strong>{n}</strong>
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
