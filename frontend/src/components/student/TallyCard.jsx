import { Briefcase, Clock, FileText } from "lucide-react";

const fmtDate = (iso) => {
  if (!iso) return "-";
  try {
    return new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    });
  } catch {
    return iso;
  }
};

export default function TallyCard({ data }) {
  if (!data || !data.history_count) {
    return (
      <div
        className="text-xs text-[var(--ayci-ink-muted)] italic"
        data-testid="tally-card-empty"
      >
        No Tally interview submissions for this email yet.
      </div>
    );
  }
  const { history = [], type, history_count } = data;
  return (
    <div className="space-y-3" data-testid="tally-card-content">
      <div className="flex items-center gap-2 text-xs text-[var(--ayci-ink-muted)]">
        <Briefcase className="w-3 h-3" />
        <span>
          {history_count} prior interview{history_count > 1 ? "s" : ""}
          {type ? ` · latest: ${type}` : ""}
        </span>
      </div>
      <div className="space-y-2">
        {history.slice(0, 8).map((h, i) => (
          <div
            key={`${h.date}-${h.submitted_at || i}`}
            className="border border-[var(--ayci-border)] rounded-md p-2.5 bg-slate-50/50"
            data-testid={`tally-history-row-${i}`}
          >
            <div className="flex items-start justify-between gap-2 flex-wrap">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-semibold text-[var(--ayci-ink)] inline-flex items-center gap-1">
                  <Clock className="w-3 h-3" /> {fmtDate(h.date)}
                </span>
                {h.type && (
                  <span
                    className={`text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded-full border ${
                      (h.type || "").toLowerCase().includes("locum")
                        ? "bg-amber-50 text-amber-700 border-amber-200"
                        : "bg-sky-50 text-sky-700 border-sky-200"
                    }`}
                  >
                    {h.type}
                  </span>
                )}
              </div>
              {h.hospital && (
                <span className="text-[10px] text-[var(--ayci-ink-muted)] truncate max-w-[200px]">
                  {h.hospital}
                </span>
              )}
            </div>
            {(h.speciality || h.outcome) && (
              <div className="text-xs text-[var(--ayci-ink-muted)] mt-1 space-y-0.5">
                {h.speciality && <div>{h.speciality}</div>}
                {h.outcome && (
                  <div className="flex items-start gap-1">
                    <FileText className="w-3 h-3 mt-0.5 flex-shrink-0" />
                    <span className="line-clamp-2">{h.outcome}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {history.length > 8 && (
          <div className="text-[10px] text-[var(--ayci-ink-muted)] italic">
            +{history.length - 8} more older interviews
          </div>
        )}
      </div>
    </div>
  );
}
