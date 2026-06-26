import { ExternalLink } from "lucide-react";

function relative(iso) {
  if (!iso) return "-";
  const then = new Date(iso);
  const now = new Date();
  const diffDays = Math.floor((now - then) / (1000 * 60 * 60 * 24));
  if (diffDays === 0) return "today";
  if (diffDays === 1) return "yesterday";
  if (diffDays < 7) return `${diffDays} days ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`;
  if (diffDays < 365) return `${Math.floor(diffDays / 30)} months ago`;
  return `${Math.floor(diffDays / 365)} years ago`;
}

export default function CircleCard({ data }) {
  if (!data) return null;
  const { name, email, avatar_url, created_at, last_seen_at, member_tags = [], profile_url } = data;

  const lastSeenDays = last_seen_at
    ? Math.floor((new Date() - new Date(last_seen_at)) / (1000 * 60 * 60 * 24))
    : null;
  const activityLabel =
    lastSeenDays === null
      ? "Never logged in"
      : lastSeenDays <= 7
      ? "Active"
      : lastSeenDays <= 30
      ? "Recently active"
      : "Dormant";
  const activityColor =
    lastSeenDays === null
      ? "bg-slate-100 text-slate-500"
      : lastSeenDays <= 7
      ? "bg-emerald-100 text-emerald-700"
      : lastSeenDays <= 30
      ? "bg-amber-100 text-amber-700"
      : "bg-rose-100 text-rose-700";

  return (
    <div className="space-y-3" data-testid="circle-card-content">
      <div className="flex items-center gap-3">
        {avatar_url && (
          <img
            src={avatar_url}
            alt={name}
            className="w-10 h-10 rounded-full object-cover border border-[var(--ayci-border)]"
          />
        )}
        <div className="flex-1">
          <div className="font-display font-semibold text-[var(--ayci-ink)]">{name}</div>
          <div className="text-xs text-[var(--ayci-ink-muted)]">{email}</div>
        </div>
        <span
          className={
            "px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider " + activityColor
          }
        >
          {activityLabel}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="bg-slate-50 rounded border border-[var(--ayci-border)] p-2">
          <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">
            Last seen
          </div>
          <div className="text-sm text-[var(--ayci-ink)] mt-0.5">{relative(last_seen_at)}</div>
        </div>
        <div className="bg-slate-50 rounded border border-[var(--ayci-border)] p-2">
          <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">
            Member since
          </div>
          <div className="text-sm text-[var(--ayci-ink)] mt-0.5">{relative(created_at)}</div>
        </div>
      </div>

      {member_tags.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] mb-1.5">
            Tags
          </div>
          <div className="flex flex-wrap gap-1.5">
            {member_tags.map((t) => (
              <span
                key={t}
                className="px-2 py-0.5 bg-violet-50 text-violet-700 border border-violet-200 rounded-full text-[11px]"
              >
                {t}
              </span>
            ))}
          </div>
        </div>
      )}

      {profile_url && (
        <a
          href={profile_url}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-[var(--ayci-teal)] hover:underline inline-flex items-center gap-1"
        >
          View Circle profile <ExternalLink className="w-3 h-3" />
        </a>
      )}
    </div>
  );
}
