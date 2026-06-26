import { useEffect, useState } from "react";
import { LifeBuoy, AlertTriangle, CheckCircle2, ArrowRight, Loader2 } from "lucide-react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

/**
 * Compact stats widget for Support Tickets, shown on the Weekly Scorecard.
 * Hides itself if the user lacks `tickets` board access.
 */
export default function SupportTicketsWidget() {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const canSee =
    user?.role === "admin" || (user?.board_access || []).includes("tickets");

  useEffect(() => {
    if (!canSee) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const { data } = await apiClient.get("/tickets/stats", { timeout: 15000 });
        if (!cancelled) setData(data);
      } catch {
        // Silently - widget is informational, not critical
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [canSee]);

  if (!canSee) return null;
  if (loading) {
    return (
      <div
        className="bg-white border border-[var(--ayci-border)] rounded-lg p-4 mb-5 shadow-sm flex items-center gap-2 text-xs text-[var(--ayci-ink-muted)]"
        data-testid="tickets-widget-loading"
      >
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        Loading support tickets…
      </div>
    );
  }
  if (!data) return null;

  const overdue = data.overdue || 0;
  const open = data.open || 0;
  const resolved = data.resolved_this_week || 0;
  const tone =
    overdue > 0
      ? "border-rose-200 bg-rose-50"
      : open > 0
      ? "border-amber-200 bg-amber-50"
      : "border-emerald-200 bg-emerald-50";

  return (
    <Link
      to="/tickets"
      className={`block border rounded-lg p-4 mb-5 shadow-sm hover:shadow-md transition-shadow ${tone}`}
      data-testid="tickets-widget"
    >
      <div className="flex items-center gap-3">
        <div className="bg-white rounded-md p-2 border border-[var(--ayci-border)]">
          <LifeBuoy className="w-5 h-5 text-[var(--ayci-accent)]" />
        </div>
        <div className="flex-1">
          <div className="text-[11px] uppercase tracking-widest font-semibold text-[var(--ayci-ink-muted)]">
            Support Tickets
          </div>
          <div className="flex items-center gap-4 mt-1.5">
            <Stat label="Open" value={open} />
            <Stat
              label="Overdue"
              value={overdue}
              icon={AlertTriangle}
              tone={overdue > 0 ? "rose" : "muted"}
            />
            <Stat
              label="Resolved 7d"
              value={resolved}
              icon={CheckCircle2}
              tone="emerald"
            />
          </div>
        </div>
        <ArrowRight className="w-4 h-4 text-[var(--ayci-ink-muted)]" />
      </div>
    </Link>
  );
}

function Stat({ label, value, icon: Icon, tone }) {
  const colour =
    tone === "rose"
      ? "text-rose-700"
      : tone === "emerald"
      ? "text-emerald-700"
      : tone === "muted"
      ? "text-[var(--ayci-ink-muted)]"
      : "text-[var(--ayci-ink)]";
  return (
    <div className="flex items-center gap-1.5">
      {Icon && <Icon className={`w-3.5 h-3.5 ${colour}`} />}
      <span className={`text-lg font-bold ${colour}`}>{value}</span>
      <span className="text-[11px] uppercase tracking-wider text-[var(--ayci-ink-muted)] font-semibold">
        {label}
      </span>
    </div>
  );
}
