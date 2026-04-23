export default function ConvertKitCard({ data }) {
  if (!data) return null;
  const { first_name, email, state, created_at, tags = [], fields = {} } = data;

  return (
    <div className="space-y-3" data-testid="convertkit-card-content">
      <div>
        <div className="font-display font-semibold text-[var(--ayci-ink)]">{first_name || "—"}</div>
        <div className="text-xs text-[var(--ayci-ink-muted)]">{email}</div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">State</div>
          <div className="text-sm mt-0.5">
            <span
              className={
                "px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider " +
                (state === "active"
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-slate-200 text-slate-600")
              }
            >
              {state || "unknown"}
            </span>
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">Subscribed</div>
          <div className="text-sm mt-0.5 text-[var(--ayci-ink)]">
            {created_at
              ? new Date(created_at).toLocaleDateString("en-GB", {
                  day: "numeric",
                  month: "short",
                  year: "numeric",
                })
              : "—"}
          </div>
        </div>
      </div>

      {tags.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] mb-1.5">
            Tags ({tags.length})
          </div>
          <div className="flex flex-wrap gap-1.5">
            {tags.map((t) => (
              <span
                key={t.id}
                className="px-2 py-0.5 bg-rose-50 text-rose-700 border border-rose-200 rounded-full text-[11px]"
              >
                {t.name}
              </span>
            ))}
          </div>
        </div>
      )}

      {Object.keys(fields).length > 0 && (
        <details>
          <summary className="text-xs text-[var(--ayci-ink-muted)] cursor-pointer hover:text-[var(--ayci-teal)]">
            Custom fields ({Object.keys(fields).length})
          </summary>
          <div className="mt-2 text-xs grid grid-cols-2 gap-2">
            {Object.entries(fields).map(([k, v]) =>
              v ? (
                <div key={k} className="border-b border-dashed border-[var(--ayci-border)] pb-1">
                  <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">{k}</div>
                  <div className="text-[var(--ayci-ink)] break-words">{String(v)}</div>
                </div>
              ) : null,
            )}
          </div>
        </details>
      )}
    </div>
  );
}
