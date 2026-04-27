import { Phone, Calendar, ChevronRight } from "lucide-react";

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

const fmtTime = (iso) => {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
};

const hostNameOnly = (full) => {
  if (!full) return null;
  // "Tessa Davis - Ace Your Consultant Interview" → "Tessa Davis"
  return full.split(/[-–]/)[0].trim();
};

export default function CalendlyCard({ data }) {
  if (!data) {
    return (
      <div
        className="text-xs text-[var(--ayci-ink-muted)] italic"
        data-testid="calendly-card-empty"
      >
        No Calendly events found for this email.
      </div>
    );
  }
  const past = data.past || [];
  const upcoming = data.upcoming || [];

  if (past.length === 0 && upcoming.length === 0) {
    return (
      <div
        className="text-xs text-[var(--ayci-ink-muted)] italic"
        data-testid="calendly-card-empty"
      >
        No active Calendly events.
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="calendly-card-content">
      {upcoming.length > 0 && (
        <Section
          icon={ChevronRight}
          label={`Upcoming (${upcoming.length})`}
          tone="emerald"
          events={upcoming}
          testid="calendly-upcoming"
          emptyMsg="No upcoming calls."
        />
      )}
      {past.length > 0 && (
        <Section
          icon={Calendar}
          label={`Past (${past.length})`}
          tone="slate"
          events={past.slice(0, 6)}
          truncated={past.length > 6 ? past.length - 6 : 0}
          testid="calendly-past"
          emptyMsg="No past calls."
        />
      )}
    </div>
  );
}

function Section({ icon: Icon, label, tone, events, truncated, testid, emptyMsg }) {
  const TONE = {
    emerald: "text-emerald-700",
    slate: "text-[var(--ayci-ink-muted)]",
  };
  if (!events.length) {
    return (
      <div className="text-xs text-[var(--ayci-ink-muted)] italic">{emptyMsg}</div>
    );
  }
  return (
    <div data-testid={testid}>
      <div
        className={`flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-subhead mb-2 ${TONE[tone]}`}
      >
        <Icon className="w-3 h-3" />
        {label}
      </div>
      <ul className="space-y-1.5">
        {events.map((e) => (
          <li
            key={e.uri || `${e.start_time}-${e.name}`}
            className="flex items-baseline justify-between gap-3 text-xs border-b border-[var(--ayci-border)] last:border-b-0 pb-1.5 last:pb-0"
          >
            <div className="flex-1 min-w-0">
              <div className="font-medium text-[var(--ayci-ink)]">
                {fmtDate(e.start_time)}{" "}
                <span className="text-[10px] font-normal text-[var(--ayci-ink-muted)]">
                  {fmtTime(e.start_time)}
                </span>
              </div>
              <div className="text-[10px] text-[var(--ayci-ink-muted)] truncate">
                {e.name}
                {hostNameOnly(e.host_name) && (
                  <>
                    {" "}
                    · with{" "}
                    <span className="text-[var(--ayci-accent)] font-semibold">
                      {hostNameOnly(e.host_name)}
                    </span>
                  </>
                )}
              </div>
            </div>
            <Phone className="w-3 h-3 text-[var(--ayci-ink-muted)] flex-shrink-0" />
          </li>
        ))}
        {truncated > 0 && (
          <li className="text-[10px] text-[var(--ayci-ink-muted)] italic pt-1">
            +{truncated} older calls
          </li>
        )}
      </ul>
    </div>
  );
}
