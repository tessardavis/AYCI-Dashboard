import { ExternalLink } from "lucide-react";

// Column titles we consider "primary" (shown first, highlighted)
const PRIMARY_KEYS = ["Tier", "Cohort", "Cohorts", "Status", "Private Chat Link", "Chat Link"];

function fmtCol(title, col) {
  if (!col) return null;
  const txt = col.text;
  if (!txt) return null;
  // Render URLs nicely
  if (typeof txt === "string" && /^https?:\/\//.test(txt.trim())) {
    return (
      <a
        href={txt}
        target="_blank"
        rel="noreferrer"
        className="text-[var(--ayci-teal)] hover:underline inline-flex items-center gap-1 break-all"
      >
        {txt} <ExternalLink className="w-3 h-3" />
      </a>
    );
  }
  return <span className="text-[var(--ayci-ink)]">{txt}</span>;
}

export default function MondayCard({ data }) {
  if (!data) return null;
  const { name, url, columns = {}, created_at } = data;

  const entries = Object.entries(columns);
  const primary = entries.filter(([k]) =>
    PRIMARY_KEYS.some((p) => k.toLowerCase().includes(p.toLowerCase())),
  );
  const rest = entries.filter(([k]) => !primary.find(([pk]) => pk === k));

  return (
    <div className="space-y-3" data-testid="monday-card-content">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-display font-semibold text-[var(--ayci-ink)]">{name}</div>
          {created_at && (
            <div className="text-[11px] text-[var(--ayci-ink-muted)]">
              Added {new Date(created_at).toLocaleDateString("en-GB")}
            </div>
          )}
        </div>
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-[var(--ayci-teal)] hover:underline inline-flex items-center gap-1"
          >
            Open in Monday <ExternalLink className="w-3 h-3" />
          </a>
        )}
      </div>

      {primary.length > 0 && (
        <div className="grid grid-cols-2 gap-3 bg-slate-50 p-3 rounded border border-[var(--ayci-border)]">
          {primary.map(([k, col]) => (
            <div key={k}>
              <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">
                {k}
              </div>
              <div className="text-sm mt-0.5 break-words">{fmtCol(k, col) || <span className="text-slate-400">—</span>}</div>
            </div>
          ))}
        </div>
      )}

      <details className="group">
        <summary className="cursor-pointer text-xs text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-teal)] select-none">
          Show all fields ({rest.length})
        </summary>
        <div className="mt-2 grid grid-cols-2 gap-3">
          {rest.map(([k, col]) => (
            <div key={k} className="border-b border-dashed border-[var(--ayci-border)] pb-2">
              <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">{k}</div>
              <div className="text-xs mt-0.5 break-words">
                {fmtCol(k, col) || <span className="text-slate-400">—</span>}
              </div>
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}
