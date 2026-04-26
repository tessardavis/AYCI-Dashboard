import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, ChevronRight, Loader2 } from "lucide-react";
import { apiClient } from "@/lib/api";

export default function AtRiskWidget() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient
      .get("/students/at-risk", { timeout: 30000 })
      .then((r) => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-4 shadow-sm flex items-center gap-2 text-xs text-[var(--ayci-ink-muted)] min-h-[120px]">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading at-risk…
      </div>
    );
  }

  if (!data) return null;

  const total = data.total_at_risk || 0;
  const top3 = (data.students || []).slice(0, 3);

  return (
    <Link
      to="/at-risk"
      className="block bg-white border border-[var(--ayci-border)] rounded-lg p-4 shadow-sm hover:shadow-md transition-shadow group"
      data-testid="at-risk-widget"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-rose-50 flex items-center justify-center">
            <AlertTriangle className="w-4 h-4 text-rose-600" />
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">
              Students at risk
            </div>
            <div className="text-[10px] text-[var(--ayci-ink-muted)]">
              ≥£{Math.round(data.min_spend_gbp || 1000)} spend · &gt;{data.dormant_days || 30}d on Circle
            </div>
          </div>
        </div>
        <ChevronRight className="w-4 h-4 text-[var(--ayci-ink-muted)] group-hover:text-[var(--ayci-teal)] transition-colors" />
      </div>

      {data.computing ? (
        <div className="text-xs text-[var(--ayci-ink-muted)] italic flex items-center gap-1">
          <Loader2 className="w-3 h-3 animate-spin" /> Scanning Stripe…
        </div>
      ) : (
        <>
          <div className="font-display font-bold text-2xl text-[var(--ayci-ink)]">
            {total}
          </div>
          <div className="text-[10px] text-[var(--ayci-ink-muted)]">
            {data.counts?.dormant || 0} dormant ·{" "}
            {(data.counts?.never_logged_in || 0) + (data.counts?.no_circle_account || 0)} no/never
          </div>
          {top3.length > 0 && (
            <div className="mt-2 space-y-1 border-t border-[var(--ayci-border)] pt-2">
              {top3.map((s) => (
                <div
                  key={s.stripe_customer_id}
                  className="flex items-center justify-between text-[11px]"
                >
                  <span className="text-[var(--ayci-ink)] truncate max-w-[140px]">
                    {s.name || s.email || "—"}
                  </span>
                  <span className="text-[var(--ayci-ink-muted)] font-semibold">
                    £{Math.round(s.lifetime_gbp).toLocaleString("en-GB")}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Link>
  );
}
