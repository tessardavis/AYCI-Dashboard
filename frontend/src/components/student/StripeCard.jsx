import { ExternalLink } from "lucide-react";

const fmtGbp = (v) =>
  `£${Number(v || 0).toLocaleString("en-GB", { maximumFractionDigits: 2 })}`;
const fmtDate = (iso) =>
  iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "—";
const fmtUnix = (ts) =>
  ts ? new Date(ts * 1000).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "—";

export default function StripeCard({ data }) {
  if (!data) return null;
  const {
    customers = [],
    total_spent_gbp,
    total_refunded_gbp,
    charge_count,
    last_charge_at,
    active_subscriptions = [],
    past_subscriptions = [],
  } = data;

  return (
    <div className="space-y-4" data-testid="stripe-card-content">
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Total spent" value={fmtGbp(total_spent_gbp)} />
        <Stat label="Payments" value={charge_count || 0} />
        <Stat label="Last charge" value={fmtDate(last_charge_at)} />
      </div>
      {Number(total_refunded_gbp) > 0 && (
        <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
          Refunded: {fmtGbp(total_refunded_gbp)}
        </div>
      )}

      {active_subscriptions.length > 0 && (
        <div>
          <div className="text-[11px] uppercase tracking-wider text-[var(--ayci-ink-muted)] mb-1.5">
            Active subscriptions
          </div>
          <div className="space-y-1.5">
            {active_subscriptions.map((s) => (
              <SubRow key={s.id} s={s} active />
            ))}
          </div>
        </div>
      )}

      {past_subscriptions.length > 0 && (
        <details>
          <summary className="text-xs text-[var(--ayci-ink-muted)] cursor-pointer hover:text-[var(--ayci-teal)]">
            Past subscriptions ({past_subscriptions.length})
          </summary>
          <div className="space-y-1.5 mt-2">
            {past_subscriptions.map((s) => (
              <SubRow key={s.id} s={s} />
            ))}
          </div>
        </details>
      )}

      <div className="pt-2 border-t border-[var(--ayci-border)] space-y-1">
        {customers.map((cu) => (
          <a
            key={cu.id}
            href={cu.url}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-[var(--ayci-teal)] hover:underline inline-flex items-center gap-1"
          >
            {cu.id} {cu.name ? `— ${cu.name}` : ""} <ExternalLink className="w-3 h-3" />
          </a>
        ))}
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="bg-slate-50 rounded border border-[var(--ayci-border)] p-2">
      <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">{label}</div>
      <div className="text-base font-semibold text-[var(--ayci-ink)] metric-number">{value}</div>
    </div>
  );
}

function SubRow({ s, active }) {
  return (
    <div className="flex items-center justify-between bg-slate-50 rounded border border-[var(--ayci-border)] p-2 text-xs">
      <div>
        <div className="font-medium text-[var(--ayci-ink)]">
          {s.product_name} — £{s.amount}/{s.interval || "once"}
        </div>
        <div className="text-[var(--ayci-ink-muted)]">
          Status: {s.status}
          {s.current_period_end && ` · Renews ${fmtUnix(s.current_period_end)}`}
        </div>
      </div>
      <span
        className={
          "px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider " +
          (active ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-600")
        }
      >
        {s.status}
      </span>
    </div>
  );
}
