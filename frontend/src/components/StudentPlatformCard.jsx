import { Loader2, AlertCircle } from "lucide-react";

export default function StudentPlatformCard({ title, platform, state, accent, children }) {
  const found = state?.found;
  const errored = !!state?.error;
  const notFound = !found && !errored;

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-lg shadow-sm overflow-hidden"
      data-testid={`platform-card-${platform}`}
    >
      <div
        className="flex items-center justify-between px-4 sm:px-5 py-3 border-b border-[var(--ayci-border)] gap-2"
        style={{ borderTopColor: accent, borderTopWidth: 3 }}
      >
        <div className="font-display font-semibold text-[var(--ayci-ink)] text-sm sm:text-base truncate">{title}</div>
        <span
          className={
            "text-[10px] uppercase tracking-wider font-medium px-2 py-0.5 rounded-full shrink-0 " +
            (found
              ? "bg-emerald-100 text-emerald-700"
              : errored
              ? "bg-amber-100 text-amber-700"
              : "bg-slate-100 text-slate-500")
          }
        >
          {found ? "Found" : errored ? "Error" : "Not found"}
        </span>
      </div>

      <div className="p-4 sm:p-5 text-sm">
        {errored && (
          <div className="flex items-start gap-2 text-amber-700 bg-amber-50 border border-amber-200 rounded p-3 text-xs">
            <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <span className="break-all">{state.error}</span>
          </div>
        )}
        {notFound && !errored && (
          <div className="text-[var(--ayci-ink-muted)] text-xs italic">
            This email has no record on this platform.
          </div>
        )}
        {found && children}
      </div>
    </div>
  );
}
