import { ExternalLink, Calendar } from "lucide-react";

const fmtDateTime = (iso) =>
  iso
    ? new Date(iso).toLocaleString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

export default function CalendlyCard({ data }) {
  if (!data) return null;
  const { events = [], total = 0 } = data;

  return (
    <div className="space-y-3" data-testid="calendly-card-content">
      <div className="text-[var(--ayci-ink-muted)] text-xs">
        <Calendar className="w-3 h-3 inline mr-1" />
        {total} past call{total === 1 ? "" : "s"} with the team
      </div>
      <div className="space-y-2">
        {events.slice(0, 10).map((ev) => (
          <div
            key={ev.uri}
            className="bg-slate-50 rounded border border-[var(--ayci-border)] p-2"
          >
            <div className="flex items-center justify-between">
              <div className="font-medium text-[var(--ayci-ink)] text-sm">{ev.name}</div>
              <span
                className={
                  "text-[10px] px-2 py-0.5 rounded-full uppercase tracking-wider " +
                  (ev.status === "active"
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-slate-200 text-slate-500")
                }
              >
                {ev.status}
              </span>
            </div>
            <div className="text-[var(--ayci-ink-muted)] text-xs mt-0.5">
              {fmtDateTime(ev.start_time)}
            </div>
            {ev.location && typeof ev.location === "string" && ev.location.startsWith("http") && (
              <a
                href={ev.location}
                target="_blank"
                rel="noreferrer"
                className="text-[11px] text-[var(--ayci-teal)] hover:underline inline-flex items-center gap-1 mt-1"
              >
                Meeting link <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </div>
        ))}
      </div>
      {events.length > 10 && (
        <div className="text-xs text-[var(--ayci-ink-muted)]">… and {events.length - 10} more</div>
      )}
    </div>
  );
}
