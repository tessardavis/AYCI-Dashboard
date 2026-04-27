import { Receipt, Tags } from "lucide-react";

const fmtDate = (iso) => {
  if (!iso) return "—";
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

const fmtGbp = (pence) => {
  const n = (pence || 0) / 100;
  return `£${n.toLocaleString("en-GB", { maximumFractionDigits: 2 })}`;
};

export default function SignupHistoryCard({ stripe, circle }) {
  const charges = (stripe?.charges || [])
    .filter((c) => c.status === "succeeded" && (c.amount || 0) > 0)
    .slice()
    .sort(
      (a, b) =>
        new Date(b.created || 0).getTime() - new Date(a.created || 0).getTime(),
    );

  const tags = (circle?.member_tags || []).filter(Boolean);
  const cohortTags = tags.filter((t) => /\d{4}|cohort|nov|feb|apr|jun|jul|aug|sep|oct|dec|jan|mar|may/i.test(t));
  const otherTags = tags.filter((t) => !cohortTags.includes(t));

  if (!charges.length && !tags.length) {
    return (
      <div className="text-xs text-[var(--ayci-ink-muted)] italic" data-testid="signup-card-empty">
        No payments or cohort tags found.
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="signup-history-card">
      {charges.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)] mb-2">
            <Receipt className="w-3 h-3" />
            Payments ({charges.length})
          </div>
          <ul className="space-y-1.5">
            {charges.slice(0, 8).map((c) => (
              <li
                key={c.id}
                className="flex items-baseline justify-between gap-2 text-xs border-b border-[var(--ayci-border)] last:border-b-0 pb-1.5 last:pb-0"
                data-testid={`signup-row-${c.id}`}
              >
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-[var(--ayci-ink)]">
                    {fmtDate(c.created)}
                  </div>
                  <div className="text-[10px] text-[var(--ayci-ink-muted)] truncate">
                    {c.description || c.product || "Stripe charge"}
                  </div>
                </div>
                <div className="font-semibold text-[var(--ayci-ink)] flex-shrink-0">
                  {fmtGbp(c.amount)}
                </div>
              </li>
            ))}
            {charges.length > 8 && (
              <li className="text-[10px] text-[var(--ayci-ink-muted)] italic pt-1">
                +{charges.length - 8} older charges
              </li>
            )}
          </ul>
        </div>
      )}

      {(cohortTags.length > 0 || otherTags.length > 0) && (
        <div>
          <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)] mb-2">
            <Tags className="w-3 h-3" />
            Circle cohort tags
          </div>
          {cohortTags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {cohortTags.map((t) => (
                <span
                  key={t}
                  className="text-[10px] px-2 py-0.5 bg-violet-50 text-violet-700 border border-violet-200 rounded-full font-semibold"
                >
                  {t}
                </span>
              ))}
            </div>
          )}
          {otherTags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {otherTags.map((t) => (
                <span
                  key={t}
                  className="text-[10px] px-2 py-0.5 bg-slate-100 text-slate-700 border border-slate-200 rounded-full"
                >
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
