/* Private-Tier Video Submissions
 *
 * DB-backed (replaces Monday board 5083952249). Reads from
 * `private_video_submissions` collection. Tessa and Becky review submissions
 * and assign / reply / mark Done from this dashboard.
 *
 * New submissions arrive via Tally webhook (form 0Qr5py → POST
 * /api/private-videos/tally-webhook) — no Monday automation involved.
 */
import { useState, useEffect, useMemo } from "react";
import { Loader2, RefreshCw, ExternalLink, Search, MessageCircle, Video, Save, X, Send, Info } from "lucide-react";
import { toast } from "sonner";
import { apiClient, formatApiErrorDetail, API } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/AuthContext";

const STATUS_OPTIONS = ["New", "Working on it", "Done", "Update name"];
const STATUS_TONE = {
  "New":            "bg-sky-100 text-sky-900 border-sky-300",
  "Working on it":  "bg-amber-100 text-amber-900 border-amber-300",
  "Done":           "bg-emerald-100 text-emerald-900 border-emerald-300",
  "Update name":    "bg-rose-100 text-rose-900 border-rose-300",
};

function formatUkDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-GB", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit", hour12: false,
    });
  } catch {
    return iso;
  }
}

// Auto-assignment helper: prefer the team_member_id linked on the user record,
// fall back to matching the team_member by name (case-insensitive, substring
// either direction). Returns "" if no usable match — caller then leaves the
// assignee dropdown blank.
function pickAutoAssignee(users, currentUser) {
  if (!users || !currentUser) return "";
  // 1. Authoritative link — server set this via _autolink_users_to_team_members.
  const tmid = currentUser.team_member_id;
  if (tmid && users.some((u) => u.id === tmid)) return tmid;
  // 2. Name match (case-insensitive substring either direction). Handles the
  //    case where the user record hasn't been auto-linked yet.
  const myName = (currentUser.name || "").trim().toLowerCase();
  if (myName) {
    const byName = users.find((u) => {
      const tn = (u.name || "").trim().toLowerCase();
      if (!tn) return false;
      return tn === myName || tn.includes(myName) || myName.includes(tn);
    });
    if (byName) return byName.id;
  }
  return "";
}

export default function PrivateVideos() {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [syncingMonday, setSyncingMonday] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [assigneeFilter, setAssigneeFilter] = useState("");
  const [editing, setEditing] = useState(null); // currently-edited row
  const [fetchedAt, setFetchedAt] = useState(null);
  // Hide "Done" by default — clears the active backlog so the team only
  // sees what still needs attention. Toggleable.
  const [showDone, setShowDone] = useState(false);

  const load = async (force = false) => {
    setRefreshing(true);
    try {
      const [{ data: list }, { data: u }] = await Promise.all([
        apiClient.get(`/private-videos${force ? "?force=true" : ""}`, { timeout: 60000 }),
        apiClient.get("/private-videos/users", { timeout: 30000 }),
      ]);
      setItems(list.items || []);
      setFetchedAt(list.fetched_at);
      setUsers(u.users || []);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to load private-tier videos");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    // First load: show whatever's in our DB instantly, then quietly sync
    // from Monday in the background so the count stays in lock-step with
    // the Monday board (which is the source of truth for replies right
    // now). The team gets a fresh-from-Monday view every time they open
    // this page, no manual button click needed.
    (async () => {
      await load();
      try {
        setSyncingMonday(true);
        const { data } = await apiClient.post(
          "/private-videos/sync-from-monday",
          {},
          { timeout: 180000 },
        );
        if ((data?.created ?? 0) > 0 || (data?.updated ?? 0) > 0) {
          await load(true);
        }
      } catch {
        // Silent — initial load was already successful, this is just a refresh
      } finally {
        setSyncingMonday(false);
      }
    })();
  }, []);

  const syncFromMonday = async () => {
    setSyncingMonday(true);
    try {
      const { data } = await apiClient.post("/private-videos/sync-from-monday", {}, { timeout: 180000 });
      const created = data?.created ?? 0;
      const updated = data?.updated ?? 0;
      toast.success(
        created === 0 && updated === 0
          ? "Already in sync with Monday"
          : `Synced from Monday — ${created} new, ${updated} updated`,
      );
      await load(true);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Sync from Monday failed");
    } finally {
      setSyncingMonday(false);
    }
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rows = items.filter((it) => {
      // Hide Done by default — user can toggle the chip below to bring them
      // back when searching historical submissions. Explicit status filter
      // (e.g. user picks "Done") always wins.
      if (!statusFilter && !showDone && (it.status || "").toLowerCase() === "done") return false;
      if (statusFilter && it.status !== statusFilter) return false;
      if (assigneeFilter === "_unassigned" && it.assignee_id) return false;
      if (assigneeFilter && assigneeFilter !== "_unassigned" && it.assignee_id !== assigneeFilter) return false;
      if (q) {
        const hay = `${it.first_name || ""} ${it.last_name || ""} ${it.email || ""} ${it.question || ""} ${it.name || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    // Active queue (not Done) — oldest submission first; the longest-waiting
    // student rises to the top so the team clears the queue fairly.
    // Done queue — newest-replied first so the most recently completed rows
    // are easy to find / re-open. (Tessa explicitly asked for this on
    // 2026-05-29 because Done rows used to bury recent completions.)
    rows.sort((a, b) => {
      const aDone = (a.status || "").toLowerCase() === "done";
      const bDone = (b.status || "").toLowerCase() === "done";
      if (aDone && bDone) {
        const ax = a.replied ? new Date(a.replied).getTime() : 0;
        const bx = b.replied ? new Date(b.replied).getTime() : 0;
        return bx - ax; // newest-replied first
      }
      const ax = a.submitted ? new Date(a.submitted).getTime() : 0;
      const bx = b.submitted ? new Date(b.submitted).getTime() : 0;
      return ax - bx; // oldest-submitted first
    });
    return rows;
  }, [items, search, statusFilter, assigneeFilter, showDone]);

  const counts = useMemo(() => {
    const c = { total: items.length, new: 0, working: 0, done: 0,
                tally: 0, monday: 0, hasAllowance: 0 };
    for (const it of items) {
      const s = (it.status || "").toLowerCase();
      if (s === "new") c.new++;
      else if (s === "working on it") c.working++;
      else if (s === "done") c.done++;
      if (it.data_source === "tally") c.tally++;
      else if (it.data_source === "monday") c.monday++;
      if (it.total_allowance) c.hasAllowance++;
    }
    return c;
  }, [items]);

  // Row-level Send: quick confirm dialog (student name + destination URL),
  // then fire /send-to-circle directly. For full preview flow the coach
  // can still go through Edit → Preview message → Send now in the modal.
  const sendNow = async (item) => {
    const replyUrl = item.reply_link?.url;
    if (!replyUrl) {
      toast.error("No voicenote link saved yet — paste one into the row first");
      return;
    }
    const studentName = `${item.first_name || ""} ${item.last_name || ""}`.trim() || item.name || item.email;
    const dest = item.private_chat;
    const confirmText =
      `Send voicenote to ${studentName} via Circle DM?\n\n` +
      `Destination: ${dest || "(no Circle DM URL on this row — Send will fail)"}\n\n` +
      `Voicenote: ${replyUrl}\n\n` +
      `This can't be undone.`;
    if (!window.confirm(confirmText)) return;
    try {
      await apiClient.post(`/private-videos/${item.id}/send-to-circle`);
      toast.success(`Sent to ${studentName} ✓`);
      load(true);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Send failed");
    }
  };

  return (
    <div className="p-4 lg:p-10 max-w-[1700px] mx-auto" data-testid="private-videos-page">
      <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
        <h1 className="font-display text-2xl lg:text-3xl font-extrabold tracking-tight text-[var(--ayci-ink)] flex items-center gap-2">
          Private-Tier Videos
          <DataSourceInfo counts={counts} />
        </h1>
        <div className="flex items-center gap-2">
          {fetchedAt && (
            <span className="text-[11px] text-[var(--ayci-ink-muted)]">
              Updated · {formatUkDate(fetchedAt)}
            </span>
          )}
          <Button variant="outline" size="sm" onClick={syncFromMonday} disabled={syncingMonday} data-testid="pv-sync-monday" title="Pull new submissions from the Monday board (preserves your edits in this dashboard)">
            {syncingMonday ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-1.5" />}
            Sync from Monday
          </Button>
          <Button variant="outline" size="sm" onClick={() => load(true)} disabled={refreshing} data-testid="pv-refresh">
            {refreshing ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-1.5" />}
            Refresh
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <StatPill label="Total" value={counts.total} tone="slate" />
        <StatPill label="New" value={counts.new} tone="sky" />
        <StatPill label="Working" value={counts.working} tone="amber" />
        <button
          type="button"
          onClick={() => setShowDone((v) => !v)}
          title={showDone ? "Hide Done from the list" : "Show Done in the list"}
          className="focus:outline-none"
          data-testid="pv-toggle-done"
        >
          <StatPill
            label={showDone ? "Done · shown" : "Done · hidden"}
            value={counts.done}
            tone={showDone ? "emerald" : "slate"}
          />
        </button>
        <div className="ml-auto flex items-center gap-1.5" title="Where these rows came from. Migrate everyone to Tally to retire the Monday board.">
          <span className="text-[10px] text-[var(--ayci-ink-muted)] uppercase tracking-wider font-semibold">Source</span>
          <span className="text-[11px] bg-sky-50 border border-sky-200 text-sky-800 px-1.5 py-0.5 rounded font-semibold" data-testid="pv-source-tally-count">
            Tally · {counts.tally}
          </span>
          <span className="text-[11px] bg-amber-50 border border-amber-200 text-amber-800 px-1.5 py-0.5 rounded font-semibold" data-testid="pv-source-monday-count">
            Monday · {counts.monday}
          </span>
        </div>
      </div>

      <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-2.5 mb-4 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text" placeholder="Search name, email, question…"
            value={search} onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 border border-slate-200 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ayci-accent)]"
            data-testid="pv-search"
          />
        </div>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="px-2 py-1.5 border border-slate-200 rounded text-sm" data-testid="pv-status-filter">
          <option value="">All status</option>
          {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={assigneeFilter} onChange={(e) => setAssigneeFilter(e.target.value)} className="px-2 py-1.5 border border-slate-200 rounded text-sm" data-testid="pv-assignee-filter">
          <option value="">All assignees</option>
          <option value="_unassigned">Unassigned</option>
          {users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
        </select>
      </div>

      {loading ? (
        <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-12 text-center text-[var(--ayci-ink-muted)]">
          <Loader2 className="w-6 h-6 animate-spin mx-auto mb-3 text-[var(--ayci-teal)]" />
          Loading…
        </div>
      ) : items.length === 0 ? (
        <EmptyStateMigrate onMigrated={() => load(true)} />
      ) : (
        <div className="bg-white border border-[var(--ayci-border)] rounded-lg overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] border-b border-[var(--ayci-border)]">
                <th className="px-3 py-2 font-semibold">Status</th>
                <th className="px-3 py-2 font-semibold">Submission</th>
                <th className="px-3 py-2 font-semibold">Question</th>
                <th className="px-3 py-2 font-semibold whitespace-nowrap">Submitted</th>
                <th className="px-3 py-2 font-semibold">Assignee</th>
                <th className="px-3 py-2 font-semibold">Replied</th>
                <th className="px-3 py-2 font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-[var(--ayci-ink-muted)] italic">
                    No submissions match the current filters.
                  </td>
                </tr>
              ) : filtered.map((it) => (
                <Row
                  key={it.id}
                  item={it}
                  users={users}
                  onEdit={() => setEditing(it)}
                  onSaved={() => load(true)}
                  onSend={sendNow}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <EditModal
          item={editing}
          users={users}
          autoAssigneeId={pickAutoAssignee(users, user)}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load(true);
          }}
        />
      )}
    </div>
  );
}

function StatPill({ label, value, tone }) {
  const cls = {
    slate: "bg-slate-100 border-slate-200 text-slate-800",
    sky: "bg-sky-100 border-sky-200 text-sky-900",
    amber: "bg-amber-100 border-amber-200 text-amber-900",
    emerald: "bg-emerald-100 border-emerald-200 text-emerald-900",
  }[tone];
  return (
    <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 border rounded-full text-xs font-semibold ${cls}`}>
      <span className="opacity-75">{label}</span>
      <span className="text-sm font-bold">{value}</span>
    </div>
  );
}


function DataSourceInfo({ counts }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative inline-flex">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        className="text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-teal)] transition-colors"
        title="Where do these counts come from?"
        data-testid="pv-data-source-info"
      >
        <Info className="w-4 h-4" />
      </button>
      {open && (
        <div
          className="absolute top-7 left-0 z-20 w-[420px] bg-white border border-[var(--ayci-border)] rounded-lg shadow-xl p-4 text-xs text-[var(--ayci-ink-muted)] space-y-2"
          data-testid="pv-data-source-popover"
        >
          <div className="font-semibold text-[var(--ayci-ink)] text-sm">How the counts are calculated</div>
          <ul className="space-y-1.5 list-disc pl-4">
            <li>
              <span className="font-semibold text-[var(--ayci-ink)]">Submission # (X/Y)</span> — the chip on each row.
              <ul className="list-disc pl-4 mt-1 space-y-0.5">
                <li><b>X</b> = count of prior submissions for that email + 1, computed locally.</li>
                <li><b>Y</b> = video allowance for that student, looked up from the Monday <i>Academy Members</i> board (column <code>numeric_mkxfvz1k</code>). Falls back to baseline by tier if missing.</li>
              </ul>
            </li>
            <li>
              <span className="font-semibold text-[var(--ayci-ink)]">Source chip</span> — every row is tagged at ingest:
              <ul className="list-disc pl-4 mt-1 space-y-0.5">
                <li><b>Tally</b>: created natively here when the student submitted the Tally form.</li>
                <li><b>Monday</b>: migrated from the Monday board sync (legacy rows + anything edited there).</li>
              </ul>
            </li>
          </ul>
          <div className="border-t border-[var(--ayci-border)] pt-2 mt-2">
            <div className="font-semibold text-[var(--ayci-ink)] mb-1">This run</div>
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              <span>Total: <b>{counts.total}</b></span>
              <span>From Tally: <b className="text-sky-700">{counts.tally}</b></span>
              <span>From Monday: <b className="text-amber-700">{counts.monday}</b></span>
              <span>With allowance: <b>{counts.hasAllowance}</b></span>
            </div>
            <p className="text-[10px] opacity-70 mt-2">
              The 493 "Monday" rows are <b>historical</b> — they were bulk-migrated when this dashboard was first wired up.
              Going forward, <b>every new submission lands as "Tally"</b> via the Tally webhook (no Monday round-trip).
              So you can already retire the Monday board for new work; the legacy column attribution just stays for reference.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}



function EmptyStateMigrate({ onMigrated }) {
  const [migrating, setMigrating] = useState(false);
  const run = async () => {
    if (!window.confirm("Pull all 462 submissions from the Monday board into the dashboard? Safe to re-run.")) return;
    setMigrating(true);
    try {
      const { data } = await apiClient.post("/private-videos/migrate-from-monday", {}, { timeout: 180000 });
      toast.success(`Migrated · created ${data.created} · updated ${data.updated}`);
      onMigrated();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Migration failed");
    } finally {
      setMigrating(false);
    }
  };
  return (
    <div
      className="bg-gradient-to-br from-violet-50 via-white to-sky-50 border-2 border-dashed border-violet-300 rounded-xl p-10 text-center"
      data-testid="pv-empty-migrate"
    >
      <Video className="w-12 h-12 text-violet-500 mx-auto mb-4" />
      <h2 className="font-display text-xl font-extrabold text-[var(--ayci-ink)] mb-2">
        No submissions yet
      </h2>
      <p className="text-sm text-[var(--ayci-ink-muted)] max-w-md mx-auto mb-6">
        Pull existing private-tier video submissions from the Monday board into
        this dashboard. After migrating, point the Tally webhook here and the
        Monday board can be retired.
      </p>
      <Button
        onClick={run}
        disabled={migrating}
        data-testid="pv-migrate-btn"
      >
        {migrating ? (
          <>
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            Migrating from Monday…
          </>
        ) : (
          <>
            <RefreshCw className="w-4 h-4 mr-2" />
            Migrate from Monday board
          </>
        )}
      </Button>
    </div>
  );
}

function Row({ item, users, onEdit, onSaved, onSend }) {
  const assignee = item.assignee_name || (users.find((u) => u.id === item.assignee_id) || {}).name || null;
  const tally = item.tally_video?.url || item.video?.url;
  const reply = item.reply_link?.url;
  const replyReady = !!reply;
  const studentName = `${item.first_name || ""} ${item.last_name || ""}`.trim() || item.name;
  const subNum = item.submission_number;
  const total = item.total_allowance;
  const hasCount = subNum !== null && subNum !== undefined && subNum !== "";
  const source = item.data_source; // "tally" | "monday" | null
  return (
    <tr className="border-b border-slate-100 hover:bg-slate-50/40">
      <td className="px-3 py-2.5">
        <span className={`inline-block text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${STATUS_TONE[item.status] || "bg-slate-100 text-slate-800 border-slate-300"}`}>
          {item.status || "—"}
        </span>
      </td>
      <td className="px-3 py-2.5">
        <div className="font-semibold text-[var(--ayci-ink)] flex items-center gap-2 flex-wrap">
          <span>{studentName}</span>
          {hasCount && (
            <span
              className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-violet-100 text-violet-800 border border-violet-200 whitespace-nowrap"
              title={
                total
                  ? `Submission #${subNum} of ${total} for this student.\nSubmission # = count of prior submissions + 1 (computed locally).\nAllowance = from the Monday Academy Members board for this email.`
                  : `Submission #${subNum} for this student. Total allowance unknown (not on Monday Academy Members).`
              }
              data-testid={`pv-count-${item.id}`}
            >
              {subNum}/{total || "—"}
            </span>
          )}
          {source && (
            <span
              className={`text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded-full border ${
                source === "tally"
                  ? "bg-sky-50 text-sky-700 border-sky-200"
                  : "bg-amber-50 text-amber-700 border-amber-200"
              }`}
              title={
                source === "tally"
                  ? "Native ingest: this row was created by the Tally webhook on submission."
                  : "Migrated row: this came from the Monday board sync."
              }
              data-testid={`pv-source-${item.id}`}
            >
              {source === "tally" ? "Tally" : "Monday"}
            </span>
          )}
        </div>
        <div className="text-[11px] text-[var(--ayci-ink-muted)]">
          {item.email || "no email"}
        </div>
      </td>
      <td className="px-3 py-2.5 max-w-[300px]">
        <div className="text-sm text-[var(--ayci-ink)] line-clamp-2">{item.question || "—"}</div>
      </td>
      <td className="px-3 py-2.5 text-[11px] text-[var(--ayci-ink-muted)] whitespace-nowrap">
        {item.submitted ? formatUkDate(item.submitted) : "—"}
      </td>
      <td className="px-3 py-2.5">
        <InlineAssignee item={item} users={users} onSaved={onSaved} />
      </td>
      <td className="px-3 py-2.5 text-[11px] text-[var(--ayci-ink-muted)] whitespace-nowrap">
        {item.replied ? formatUkDate(item.replied) : "—"}
      </td>
      <td className="px-3 py-2.5">
        <div className="flex items-center gap-1.5 flex-wrap">
          {tally && (
            <a
              href={`${API}/private-videos/${item.id}/video`}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-rose-700 hover:underline flex items-center gap-0.5"
              title="Watch the student's video (mobile-friendly H.264)"
            >
              <Video className="w-3 h-3" /> Video
            </a>
          )}
          <InlineReplyLink item={item} onSaved={onSaved} />
          {replyReady && (
            <span
              className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 border border-emerald-300 whitespace-nowrap"
              title="A voicenote URL is saved on this row — it's ready to send."
              data-testid={`pv-voicenote-ready-${item.id}`}
            >
              ✓ Voicenote
            </span>
          )}
          {item.private_chat && (
            <a href={item.private_chat} target="_blank" rel="noreferrer" className="text-xs text-sky-700 hover:underline flex items-center gap-0.5" title="Open Circle DM thread">
              <ExternalLink className="w-3 h-3" /> Circle
            </a>
          )}
          {replyReady && (
            <button
              onClick={() => onSend?.(item)}
              className="text-xs px-2 py-0.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white font-semibold inline-flex items-center gap-0.5"
              title="Send the voicenote to this student's Circle DM. You'll get a quick confirm before it fires."
              data-testid={`pv-send-${item.id}`}
            >
              <Send className="w-3 h-3" /> Send
            </button>
          )}
          <button
            onClick={onEdit}
            className="text-xs px-2 py-0.5 rounded border border-slate-200 hover:bg-slate-100 font-semibold text-slate-700"
            data-testid={`pv-edit-${item.id}`}
          >
            Edit
          </button>
        </div>
      </td>
    </tr>
  );
}

// Click an assignee chip → dropdown → patch in place. No modal, no scroll.
function InlineAssignee({ item, users, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const currentName = item.assignee_name
    || (users.find((u) => u.id === item.assignee_id) || {}).name
    || null;

  const save = async (newId) => {
    setSaving(true);
    try {
      await apiClient.patch(`/private-videos/${item.id}`, {
        assignee_id: newId || "",
      });
      toast.success(newId ? "Assigned" : "Unassigned");
      onSaved?.();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Couldn't assign");
    } finally {
      setSaving(false);
      setEditing(false);
    }
  };

  if (editing) {
    return (
      <select
        autoFocus
        defaultValue={item.assignee_id || ""}
        disabled={saving}
        onChange={(e) => save(e.target.value)}
        onBlur={() => setEditing(false)}
        className="text-xs px-1.5 py-0.5 rounded border border-[var(--ayci-accent)] bg-white focus:outline-none focus:ring-2 focus:ring-[var(--ayci-accent)]/30 max-w-[160px]"
        data-testid={`pv-inline-assignee-${item.id}`}
      >
        <option value="">— unassigned —</option>
        {users.map((u) => (
          <option key={u.id} value={u.id}>{u.name}</option>
        ))}
      </select>
    );
  }
  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      className={`text-xs px-1.5 py-0.5 rounded font-semibold border transition-colors ${currentName ? "bg-sky-100 text-sky-800 border-sky-200 hover:bg-sky-200" : "bg-amber-50 text-amber-700 border-amber-200 italic hover:bg-amber-100"}`}
      title="Click to change assignee"
      data-testid={`pv-inline-assignee-button-${item.id}`}
    >
      {currentName || "unassigned"}
    </button>
  );
}

// Click "+ Reply" / pencil → tiny inline input → patch in place. Only the
// reply_link is stored; status + replied date are set later when the coach
// actually sends via the modal's Preview → Send now flow.
function InlineReplyLink({ item, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(item.reply_link?.url || "");
  const [saving, setSaving] = useState(false);
  const reply = item.reply_link?.url;

  const save = async () => {
    const url = value.trim();
    setSaving(true);
    try {
      // Inline edit only stores the URL. The row is NOT marked Done and the
      // Replied date is NOT set — completion belongs to "Send to Circle" in
      // the edit modal, which actually delivers the voicenote to the student.
      // Previously this auto-marked Done and looked like the reply had been
      // sent when it hadn't.
      await apiClient.patch(`/private-videos/${item.id}`, {
        reply_link: url,
      });
      toast.success(
        url
          ? "Reply link saved — open Edit → Preview → Send now to deliver"
          : "Reply link cleared"
      );
      onSaved?.();
      setEditing(false);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (editing) {
    return (
      <span className="inline-flex items-center gap-1">
        <input
          autoFocus
          type="url"
          value={value}
          placeholder="https://voicenotes.com/s/…"
          disabled={saving}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") { setValue(item.reply_link?.url || ""); setEditing(false); }
          }}
          className="text-xs px-1.5 py-0.5 rounded border border-[var(--ayci-accent)] bg-white focus:outline-none focus:ring-2 focus:ring-[var(--ayci-accent)]/30 w-[200px]"
          data-testid={`pv-inline-reply-input-${item.id}`}
        />
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="text-xs px-1.5 py-0.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white font-semibold"
          data-testid={`pv-inline-reply-save-${item.id}`}
        >
          {saving ? "…" : "Save"}
        </button>
        <button
          type="button"
          onClick={() => { setValue(item.reply_link?.url || ""); setEditing(false); }}
          className="text-xs px-1 py-0.5 text-slate-500 hover:text-slate-700"
        >
          ✕
        </button>
      </span>
    );
  }

  if (reply) {
    return (
      <span className="inline-flex items-center gap-0.5">
        <a href={reply} target="_blank" rel="noreferrer" className="text-xs text-emerald-700 hover:underline flex items-center gap-0.5" title="Coach voicenote reply">
          <MessageCircle className="w-3 h-3" /> Reply
        </a>
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="text-[10px] text-slate-400 hover:text-slate-700 px-0.5"
          title="Edit reply link"
          data-testid={`pv-inline-reply-edit-${item.id}`}
        >
          ✎
        </button>
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      className="text-xs text-emerald-700 hover:bg-emerald-50 px-1.5 py-0.5 rounded border border-dashed border-emerald-300 hover:border-emerald-500 inline-flex items-center gap-0.5 font-medium"
      data-testid={`pv-inline-reply-add-${item.id}`}
    >
      <MessageCircle className="w-3 h-3" /> + Reply
    </button>
  );
}

function EditModal({ item, users, autoAssigneeId, onClose, onSaved }) {
  const originalReplyLink = item.reply_link?.url || "";
  const [statusLabel, setStatusLabel] = useState(item.status || "");
  // Auto-default Assignee to the current user (resolved by parent) if the
  // row has none. Coach can still re-pick a teammate from the dropdown.
  const [assigneeId, setAssigneeId] = useState(item.assignee_id || autoAssigneeId || "");
  const [replyLink, setReplyLink] = useState(originalReplyLink);
  // No editable "Replied date" — the backend stamps it automatically when
  // Send now succeeds. Showing an empty date field made it look amendable.

  // If the coach is editing a Done row's reply link, flip the status
  // dropdown out of "Done" automatically — saving without re-sending
  // shouldn't leave the row marked as delivered. They can manually pick
  // "Done" again if they really want to keep the old completion stamp.
  useEffect(() => {
    if (
      statusLabel === "Done" &&
      replyLink.trim() &&
      replyLink.trim() !== originalReplyLink.trim()
    ) {
      setStatusLabel("New");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replyLink]);
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState(false);
  const [preview, setPreview] = useState(null);       // null = preview not opened
  const [previewing, setPreviewing] = useState(false);

  const openPreview = async () => {
    const url = (replyLink || "").trim();
    if (!url) {
      toast.error("Add the voicenote URL first");
      return;
    }
    setPreviewing(true);
    try {
      // Save current modal state first so the preview reflects what'd actually be sent
      await apiClient.patch(`/private-videos/${item.id}`, {
        status_label: statusLabel,
        assignee_id: assigneeId || "",
        reply_link: url,
      });
      const { data } = await apiClient.get(
        `/private-videos/${item.id}/send-to-circle-preview`,
      );
      setPreview(data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Preview failed");
    } finally {
      setPreviewing(false);
    }
  };

  const sendFromPreview = async () => {
    setSending(true);
    try {
      await apiClient.post(`/private-videos/${item.id}/send-to-circle`);
      toast.success("Sent to Circle ✓ — marked Done");
      onSaved();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Send failed");
    } finally {
      setSending(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.patch(`/private-videos/${item.id}`, {
        status_label: statusLabel,
        assignee_id: assigneeId || "",
        reply_link: replyLink,
      });
      toast.success("Saved");
      onSaved();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-end lg:items-center justify-center p-2 lg:p-6" onClick={onClose}>
      <div className="bg-white rounded-lg max-w-2xl w-full max-h-[92vh] overflow-y-auto shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="p-4 border-b border-slate-200 flex items-start justify-between gap-3">
          <div>
            <div className="font-display text-lg font-extrabold text-[var(--ayci-ink)]">{item.name}</div>
            <div className="text-[11px] text-[var(--ayci-ink-muted)] mt-0.5">
              {item.email} · video {item.submission_number}/{item.total_allowance}
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-4 space-y-4">
          {item.question && (
            <div>
              <Label>Question</Label>
              <div className="text-sm bg-slate-50 border border-slate-200 rounded p-2.5 text-[var(--ayci-ink)]">
                {item.question}
              </div>
            </div>
          )}
          {(item.tally_video?.url || item.video?.url) && (
            <div>
              <Label>Student video</Label>
              <InlineVideo itemId={item.id} />
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <Label>Status</Label>
              <select value={statusLabel} onChange={(e) => setStatusLabel(e.target.value)} className={inputCls} data-testid="pv-edit-status">
                {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <Label>Assignee</Label>
              <select value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)} className={inputCls} data-testid="pv-edit-assignee">
                <option value="">Unassigned</option>
                {users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
              </select>
            </div>
            <div>
              <Label>Reply link (voicenote URL)</Label>
              <input
                type="url"
                value={replyLink}
                onChange={(e) => setReplyLink(e.target.value)}
                placeholder="https://www.voicenotes.com/s/…"
                className={inputCls}
                data-testid="pv-edit-reply"
              />
            </div>
          </div>

          {item.private_chat && (
            <div className="text-xs text-[var(--ayci-ink-muted)] bg-sky-50 border border-sky-200 rounded p-2 flex items-start gap-2">
              <MessageCircle className="w-3.5 h-3.5 text-sky-700 mt-0.5 shrink-0" />
              <div>
                Clicking <strong>Preview message</strong> below shows the exact rendered message + destination. From the preview you click <strong>Send now</strong> to post the voicenote to{" "}
                <a href={item.private_chat} target="_blank" rel="noreferrer" className="text-sky-700 font-semibold hover:underline">
                  this Circle Group DM
                </a>{" "}
                via Zapier (marks the submission Done).
              </div>
            </div>
          )}

          {preview && (
            <div className="border-2 border-emerald-400 bg-emerald-50/60 rounded-md p-3 space-y-2.5">
              <div className="flex items-start gap-2">
                <Send className="w-4 h-4 text-emerald-700 mt-0.5 shrink-0" />
                <div className="flex-1">
                  <div className="text-xs font-bold uppercase tracking-wider text-emerald-800">Preview — nothing has been sent yet</div>
                  <div className="text-[11px] text-emerald-700/80 mt-0.5">
                    Verify the destination + message below. Then click <strong>Send now</strong> to deliver, or <strong>Back</strong> to edit.
                  </div>
                </div>
              </div>
              <div className="text-xs space-y-1.5">
                <div><span className="font-semibold">To:</span> {preview.student_name} ({preview.student_email})</div>
                <div>
                  <span className="font-semibold">Destination DM:</span>{" "}
                  {preview.destination ? (
                    <a href={preview.destination} target="_blank" rel="noreferrer" className="text-sky-700 hover:underline break-all">{preview.destination}</a>
                  ) : (
                    <span className="text-red-700 font-semibold">⚠ MISSING</span>
                  )}
                </div>
                <div><span className="font-semibold">Coach:</span> {preview.coach_name}</div>
                {preview.submission_number && preview.total_allowance && (
                  <div><span className="font-semibold">Counter:</span> submission {preview.submission_number} of {preview.total_allowance}</div>
                )}
                {!!preview.warnings?.length && (
                  <div className="bg-amber-100 border border-amber-300 rounded p-2 mt-1">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-amber-800 mb-1">Warnings</div>
                    <ul className="list-disc ml-4 text-[11px] text-amber-900 space-y-0.5">
                      {preview.warnings.map((w, i) => <li key={i}>{w}</li>)}
                    </ul>
                  </div>
                )}
              </div>
              <div>
                <Label>Message that will be posted</Label>
                <pre className="text-xs bg-white border border-slate-200 rounded p-3 whitespace-pre-wrap font-sans leading-relaxed">{preview.message_text}</pre>
              </div>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-3 border-t border-slate-100 flex-wrap">
            {preview ? (
              <>
                <Button variant="outline" onClick={() => setPreview(null)} disabled={sending}>
                  ← Back
                </Button>
                <Button
                  onClick={sendFromPreview}
                  disabled={sending || !preview.destination || !preview.zapier_configured}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white"
                  data-testid="pv-edit-send-confirmed"
                  title={
                    !preview.zapier_configured
                      ? "Zapier webhook not configured (see warning above) — Send will fail"
                      : !preview.destination
                        ? "Can't send — no destination Circle DM URL on this row"
                        : "Deliver this message now"
                  }
                >
                  {sending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Send className="w-4 h-4 mr-2" />}
                  Send now
                </Button>
              </>
            ) : (
              <>
                <Button variant="outline" onClick={onClose} disabled={saving || sending || previewing}>Cancel</Button>
                <Button
                  variant="outline"
                  onClick={save}
                  disabled={saving || sending || previewing}
                  data-testid="pv-edit-save"
                >
                  {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
                  Save
                </Button>
                <Button
                  variant="outline"
                  onClick={openPreview}
                  disabled={saving || sending || previewing || !replyLink.trim()}
                  data-testid="pv-edit-preview"
                  title={!replyLink.trim() ? "Add the voicenote URL first" : "See exactly what will be sent before sending"}
                >
                  {previewing ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
                  Preview message
                </Button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Label({ children }) {
  return <div className="text-[10px] uppercase tracking-wider font-bold text-[var(--ayci-ink-muted)] mb-1">{children}</div>;
}
const inputCls = "w-full px-3 py-1.5 border border-slate-200 rounded text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[var(--ayci-accent)]";

// Inline `<video>` so coaches can watch on mobile + desktop without
// leaving the app. Backend pipeline:
//   1. download from Tally → disk
//   2. detect codec; if HEVC (iPhone default), transcode → H.264
//   3. serve from disk with proper Range support
// First load takes ~30-90s (download + transcode); we poll the status
// endpoint and show progress so the user knows it's working.
function InlineVideo({ itemId }) {
  const [errored, setErrored] = useState(false);
  // Lazy-load: don't poll / transcode until the coach clicks Play. The
  // transcode is 10-30s on first hit and most coaches don't need to watch
  // every video to compose a reply — they have the question text already.
  const [started, setStarted] = useState(false);
  const [status, setStatus] = useState("idle");
  const proxyUrl = `${API}/private-videos/${itemId}/video`;

  useEffect(() => {
    if (!started) return;
    let cancelled = false;
    let pollTimer = null;
    const poll = async () => {
      try {
        const { data } = await apiClient.get(`/private-videos/${itemId}/video/status`);
        if (cancelled) return;
        setStatus(data.status);
        if (data.status === "ready") return;
        if (data.status === "error" || data.status === "no_video") return;
        pollTimer = setTimeout(poll, 3000);
      } catch {
        if (!cancelled) {
          setStatus("error");
        }
      }
    };
    poll();
    return () => {
      cancelled = true;
      if (pollTimer) clearTimeout(pollTimer);
    };
  }, [itemId, started]);

  if (!started) {
    return (
      <button
        type="button"
        onClick={() => setStarted(true)}
        className="w-full aspect-video rounded-md bg-slate-100 border border-slate-200 hover:bg-slate-200/70 hover:border-slate-300 transition flex flex-col items-center justify-center gap-2 text-[var(--ayci-ink-muted)] px-4 text-center group"
        data-testid="pv-video-play"
        title="Load and play the student's video (first load ~10-30s while we transcode for your browser)"
      >
        <div className="w-12 h-12 rounded-full bg-white border border-slate-300 group-hover:border-[var(--ayci-accent)] group-hover:bg-[var(--ayci-accent)] flex items-center justify-center transition">
          <Video className="w-5 h-5 text-[var(--ayci-accent)] group-hover:text-white transition" />
        </div>
        <div className="text-xs font-semibold text-[var(--ayci-ink)]">Play student video</div>
        <div className="text-[10px]">First load ~10-30s · cached after that</div>
      </button>
    );
  }

  if (errored || status === "error" || status === "no_video") {
    // Inline `<video>` couldn't play. We ALWAYS route the fallback to our
    // proxy URL, which serves the transcoded H.264 — not the raw Tally URL,
    // because iPhone Chrome can't decode HEVC from non-Apple domains.
    return (
      <a
        href={proxyUrl}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1.5 text-sm text-rose-700 hover:underline font-semibold"
        data-testid="pv-video-fallback"
      >
        <Video className="w-4 h-4" /> Open video in new tab
      </a>
    );
  }

  if (status !== "ready") {
    const labels = {
      loading: { title: "Loading…", sub: "" },
      missing: { title: "Preparing video…", sub: "Starting download from Tally" },
      downloading: { title: "Downloading from Tally…", sub: "First load only — usually 10-30s" },
      downloaded: { title: "Almost ready…", sub: "Optimising for your browser" },
      transcoding: { title: "Optimising for your browser…", sub: "Converting iPhone HEVC → universal H.264 (~60-90s)" },
    };
    const l = labels[status] || labels.loading;
    return (
      <div
        className="w-full aspect-video rounded-md bg-slate-100 border border-slate-200 flex flex-col items-center justify-center gap-2 text-[var(--ayci-ink-muted)] px-4 text-center"
        data-testid="pv-video-warming"
      >
        <Loader2 className="w-6 h-6 animate-spin text-[var(--ayci-accent)]" />
        <div className="text-xs font-semibold text-[var(--ayci-ink)]">{l.title}</div>
        {l.sub && <div className="text-[10px]">{l.sub}</div>}
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <video
        src={proxyUrl}
        controls
        playsInline
        preload="metadata"
        className="w-full max-h-[60vh] rounded-md bg-black"
        onError={() => setErrored(true)}
        data-testid="pv-video-player"
      >
        Your browser can't play this video.
      </video>
    </div>
  );
}
