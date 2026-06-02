import { useEffect, useMemo, useState } from "react";
import {
  LifeBuoy,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  X,
  AlertTriangle,
  Clock,
  Send,
  Mail,
  ExternalLink,
  Filter,
  LayoutGrid,
  Rows,
  MessageCircle,
  Paperclip,
  FileText,
  Download,
  Lock,
  XCircle,
  Calendar,
} from "lucide-react";
import { toast } from "sonner";
import { apiClient, formatApiErrorDetail, API } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";

const STATUSES = [
  { value: "open", label: "Open", chip: "bg-rose-50 text-rose-800 border-rose-200" },
  { value: "in_progress", label: "In Progress", chip: "bg-amber-50 text-amber-800 border-amber-200" },
  { value: "waiting", label: "Waiting on Student", chip: "bg-violet-50 text-violet-800 border-violet-200" },
  { value: "resolved", label: "Resolved", chip: "bg-emerald-50 text-emerald-800 border-emerald-200" },
  { value: "closed", label: "Closed", chip: "bg-slate-100 text-slate-700 border-slate-300" },
];
const STATUS_META = Object.fromEntries(STATUSES.map((s) => [s.value, s]));

const PRIORITIES = [
  { value: "urgent", label: "Urgent", chip: "bg-rose-600 text-white border-rose-700" },
  { value: "high", label: "High", chip: "bg-orange-100 text-orange-900 border-orange-300" },
  { value: "medium", label: "Medium", chip: "bg-sky-100 text-sky-900 border-sky-300" },
  { value: "low", label: "Low", chip: "bg-slate-100 text-slate-700 border-slate-300" },
];
const PRIORITY_META = Object.fromEntries(PRIORITIES.map((p) => [p.value, p]));

const CATEGORIES = [
  { value: "billing", label: "Billing" },
  { value: "tech", label: "Tech" },
  { value: "coaching", label: "Coaching" },
  { value: "refund", label: "Refund" },
  { value: "other", label: "Other" },
];

const SOURCE_LABEL = { manual: "Manual", tally: "Form", email: "Email", whatsapp: "WhatsApp" };

function formatUk(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/London",
  });
}

function relativeAge(iso) {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  const h = Math.floor(ms / 3600000);
  if (h < 1) return `${Math.max(1, Math.floor(ms / 60000))}m ago`;
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

// Live Wati pipeline health indicator. Polls /api/wati/health every 60s,
// shows a green/amber/grey dot + last-reconcile timestamp, with a "Sync now"
// click action so the team can force a reconcile when they're worried.
function WatiHealthBadge() {
  const [health, setHealth] = useState(null);
  const [syncing, setSyncing] = useState(false);

  const refresh = async () => {
    try {
      const { data } = await apiClient.get("/wati/health");
      setHealth(data);
    } catch {
      setHealth({ configured: false });
    }
  };

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 60_000);
    return () => clearInterval(t);
  }, []);

  const forceReconcile = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (syncing) return;
    setSyncing(true);
    try {
      const { data } = await apiClient.post("/wati/reconcile");
      toast.success(
        data.appended
          ? `Recovered ${data.appended} WhatsApp message${data.appended === 1 ? "" : "s"}`
          : "WhatsApp inbox in sync — nothing missed",
      );
      await refresh();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Reconcile failed");
    } finally {
      setSyncing(false);
    }
  };

  if (!health) return null;
  if (!health.configured) return null;

  const ranAt = health.ran_at ? new Date(health.ran_at).getTime() : 0;
  const ageMin = ranAt ? Math.round((Date.now() - ranAt) / 60_000) : null;
  const errored = (health.errors?.length || 0) > 0;
  const stale = ageMin == null || ageMin > 12;
  const tone = errored
    ? "bg-rose-50 text-rose-800 border-rose-200"
    : stale
      ? "bg-amber-50 text-amber-800 border-amber-200"
      : "bg-emerald-50 text-emerald-800 border-emerald-200";
  const dotTone = errored ? "bg-rose-500" : stale ? "bg-amber-500" : "bg-emerald-500";
  const label = errored
    ? "WhatsApp · errors"
    : ranAt
      ? `WhatsApp · synced ${ageMin <= 0 ? "just now" : `${ageMin}m ago`}`
      : "WhatsApp · pending sync";
  const tooltip = errored
    ? `Last sync had errors: ${health.errors.join(", ")}`
    : `Auto-reconciles every 5 min. Last run: ${
        ranAt ? new Date(ranAt).toLocaleString("en-GB") : "—"
      }. Click to sync now.`;

  return (
    <button
      onClick={forceReconcile}
      disabled={syncing}
      title={tooltip}
      data-testid="wati-health-badge"
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[11px] font-semibold ${tone} hover:shadow-sm transition-all disabled:opacity-50`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${dotTone} ${errored ? "" : "animate-pulse"}`} />
      {syncing ? (
        <>
          <Loader2 className="w-3 h-3 animate-spin" />
          Syncing…
        </>
      ) : (
        <>
          <MessageCircle className="w-3 h-3" />
          {label}
        </>
      )}
    </button>
  );
}

export default function SupportTickets() {
  const { user } = useAuth();
  const [tickets, setTickets] = useState([]);
  const [team, setTeam] = useState([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState("kanban"); // "kanban" | "table"
  const [search, setSearch] = useState("");
  const [filterPriority, setFilterPriority] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [filterAssignee, setFilterAssignee] = useState("");
  const [mineOnly, setMineOnly] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [activeId, setActiveId] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [showOlder, setShowOlder] = useState(false);
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [confirmBulkClose, setConfirmBulkClose] = useState(false);
  const [bulkClosing, setBulkClosing] = useState(false);

  // Hide historical Tally noise: only show tickets created on/after this cutoff
  // unless the user explicitly toggles "Show older".
  const SINCE_CUTOFF_MS = useMemo(
    () => new Date("2026-05-05T00:00:00+01:00").getTime(),
    [],
  );

  const myTeamId = user?.team_member_id || null;
  const teamById = useMemo(() => Object.fromEntries(team.map((t) => [t.id, t])), [team]);

  const load = async () => {
    setLoading(true);
    try {
      const [tRes, teamRes] = await Promise.all([
        apiClient.get("/tickets"),
        apiClient.get("/team"),
      ]);
      setTickets(tRes.data.tickets || []);
      setTeam(teamRes.data || []);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load tickets");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return tickets.filter((t) => {
      if (!showOlder && t.created_at) {
        const ts = new Date(t.created_at).getTime();
        if (Number.isFinite(ts) && ts < SINCE_CUTOFF_MS) return false;
      }
      if (filterPriority && t.priority !== filterPriority) return false;
      if (filterCategory && t.category !== filterCategory) return false;
      if (filterAssignee === "_unassigned" && t.assignee_id) return false;
      if (filterAssignee && filterAssignee !== "_unassigned" && t.assignee_id !== filterAssignee) return false;
      if (mineOnly) {
        if (!myTeamId) return false;
        if (t.assignee_id !== myTeamId) return false;
      }
      if (q) {
        const hay = `${t.student_name} ${t.student_email} ${t.subject} ${t.description}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [tickets, search, filterPriority, filterCategory, filterAssignee, mineOnly, myTeamId, showOlder, SINCE_CUTOFF_MS]);

  const olderHiddenCount = useMemo(() => {
    if (showOlder) return 0;
    return tickets.filter((t) => {
      const ts = t.created_at ? new Date(t.created_at).getTime() : NaN;
      return Number.isFinite(ts) && ts < SINCE_CUTOFF_MS;
    }).length;
  }, [tickets, showOlder, SINCE_CUTOFF_MS]);

  const grouped = useMemo(() => {
    const out = Object.fromEntries(STATUSES.map((s) => [s.value, []]));
    filtered.forEach((t) => {
      if (out[t.status]) out[t.status].push(t);
    });
    return out;
  }, [filtered]);

  const counts = useMemo(() => {
    const inWindow = showOlder
      ? tickets
      : tickets.filter((t) => {
          const ts = t.created_at ? new Date(t.created_at).getTime() : NaN;
          return !Number.isFinite(ts) || ts >= SINCE_CUTOFF_MS;
        });
    const open = inWindow.filter((t) => ["open", "in_progress", "waiting"].includes(t.status));
    return {
      total_open: open.length,
      overdue: open.filter((t) => t.overdue).length,
      urgent: open.filter((t) => t.priority === "urgent").length,
      mine: myTeamId
        ? inWindow.filter(
            (t) =>
              t.assignee_id === myTeamId &&
              ["open", "in_progress", "waiting"].includes(t.status),
          ).length
        : 0,
    };
  }, [tickets, myTeamId, showOlder, SINCE_CUTOFF_MS]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      const { data } = await apiClient.post("/tickets/tally/sync");
      toast.success(`Tally sync: ${data.inserted} new ticket${data.inserted === 1 ? "" : "s"} (scanned ${data.scanned})`);
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Tally sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const updateTicket = async (id, patch) => {
    try {
      const { data } = await apiClient.patch(`/tickets/${id}`, patch);
      setTickets((prev) => prev.map((t) => (t.id === id ? data : t)));
      return data;
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Update failed");
    }
  };

  const handleCreate = async (form) => {
    try {
      const { data } = await apiClient.post("/tickets", form);
      setTickets((prev) => [data, ...prev]);
      setCreateOpen(false);
      toast.success("Ticket created");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Create failed");
    }
  };

  const activeTicket = tickets.find((t) => t.id === activeId);

  const toggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Add/remove a whole list of ids at once. `nextChecked` is the desired state.
  const toggleSelectMany = (ids, nextChecked) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (nextChecked) ids.forEach((id) => next.add(id));
      else ids.forEach((id) => next.delete(id));
      return next;
    });
  };

  const clearSelection = () => setSelectedIds(new Set());

  const handleBulkClose = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    setBulkClosing(true);
    try {
      const { data } = await apiClient.post("/tickets/bulk-close", { ids });
      const closed = data?.closed ?? 0;
      toast.success(
        closed === 0
          ? "Nothing to close — selected tickets were already closed"
          : `Closed ${closed} ticket${closed === 1 ? "" : "s"}`,
      );
      setConfirmBulkClose(false);
      clearSelection();
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Bulk close failed");
    } finally {
      setBulkClosing(false);
    }
  };

  return (
    <div className="p-4 lg:p-10 max-w-[1600px] mx-auto" data-testid="support-tickets-page">
      {/* Compact header: title + actions in one row, slim stat strip below */}
      <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="font-display text-2xl lg:text-3xl font-extrabold tracking-tight text-[var(--ayci-ink)]">
            Support Tickets
          </h1>
          <WatiHealthBadge />
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleSync}
            disabled={syncing}
            data-testid="tickets-sync-tally"
          >
            {syncing ? (
              <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4 mr-1.5" />
            )}
            Sync Tally
          </Button>
          <Button onClick={() => setCreateOpen(true)} size="sm" data-testid="tickets-new-button">
            <Plus className="w-4 h-4 mr-1.5" />
            New
          </Button>
        </div>
      </div>

      {/* Slim inline stats strip */}
      <div
        className="flex items-center gap-2 mb-3 overflow-x-auto pb-1 -mx-1 px-1"
        data-testid="ticket-stats-strip"
      >
        <StatPill label="Open" value={counts.total_open} tone="slate" testid="ticket-stat-open" />
        <StatPill
          label="Overdue"
          value={counts.overdue}
          tone={counts.overdue > 0 ? "rose" : "emerald"}
          icon={AlertTriangle}
          testid="ticket-stat-overdue"
        />
        <StatPill
          label="Urgent"
          value={counts.urgent}
          tone={counts.urgent > 0 ? "rose" : "slate"}
          testid="ticket-stat-urgent"
        />
        <StatPill label="Mine" value={counts.mine} tone="sky" testid="ticket-stat-mine" />
        {olderHiddenCount > 0 && (
          <button
            onClick={() => setShowOlder(true)}
            className="ml-auto text-[11px] font-semibold text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-accent)] underline-offset-2 hover:underline whitespace-nowrap"
            data-testid="tickets-show-older"
            title="Show tickets created before 5 May 2026"
          >
            +{olderHiddenCount} older
          </button>
        )}
        {showOlder && (
          <button
            onClick={() => setShowOlder(false)}
            className="ml-auto text-[11px] font-semibold text-[var(--ayci-accent)] hover:underline whitespace-nowrap"
            data-testid="tickets-hide-older"
          >
            Hide older
          </button>
        )}
      </div>

      {/* Toolbar */}
      <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-2.5 mb-4 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[var(--ayci-ink-muted)]" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search subject, student, email…"
            className="w-full pl-9 pr-3 py-2 text-sm border border-[var(--ayci-border)] rounded-md focus:outline-none focus:ring-2 focus:ring-[var(--ayci-accent)]/40"
            data-testid="tickets-search-input"
          />
        </div>
        <Select
          value={filterPriority}
          onChange={setFilterPriority}
          placeholder="All priorities"
          options={PRIORITIES.map((p) => ({ value: p.value, label: p.label }))}
          testid="tickets-filter-priority"
        />
        <Select
          value={filterCategory}
          onChange={setFilterCategory}
          placeholder="All categories"
          options={CATEGORIES}
          testid="tickets-filter-category"
        />
        <Select
          value={filterAssignee}
          onChange={setFilterAssignee}
          placeholder="All assignees"
          options={[
            { value: "_unassigned", label: "Unassigned" },
            ...team.map((t) => ({ value: t.id, label: t.name })),
          ]}
          testid="tickets-filter-assignee"
        />
        <label
          className={[
            "flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-md border cursor-pointer transition-colors",
            mineOnly
              ? "bg-[var(--ayci-accent)] text-white border-[var(--ayci-accent)]"
              : "bg-white text-[var(--ayci-ink-muted)] border-[var(--ayci-border)] hover:border-[var(--ayci-accent)]",
          ].join(" ")}
          data-testid="tickets-mine-only-toggle"
        >
          <input
            type="checkbox"
            checked={mineOnly}
            onChange={(e) => setMineOnly(e.target.checked)}
            className="hidden"
          />
          My tickets
        </label>
        <div className="ml-auto flex items-center gap-1 bg-slate-100 rounded-md p-0.5">
          <button
            onClick={() => setView("kanban")}
            data-testid="tickets-view-kanban"
            className={[
              "flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded transition-colors",
              view === "kanban" ? "bg-white shadow-sm text-[var(--ayci-ink)]" : "text-[var(--ayci-ink-muted)]",
            ].join(" ")}
          >
            <LayoutGrid className="w-3.5 h-3.5" />
            Kanban
          </button>
          <button
            onClick={() => setView("table")}
            data-testid="tickets-view-table"
            className={[
              "flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded transition-colors",
              view === "table" ? "bg-white shadow-sm text-[var(--ayci-ink)]" : "text-[var(--ayci-ink-muted)]",
            ].join(" ")}
          >
            <Rows className="w-3.5 h-3.5" />
            Table
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20 text-sm text-[var(--ayci-ink-muted)]">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading tickets…
        </div>
      ) : view === "kanban" ? (
        <KanbanBoard
          grouped={grouped}
          teamById={teamById}
          onOpen={setActiveId}
          onUpdate={updateTicket}
          selectedIds={selectedIds}
          onToggleSelect={toggleSelect}
          onToggleSelectMany={toggleSelectMany}
        />
      ) : (
        <TicketTable
          rows={filtered}
          teamById={teamById}
          onOpen={setActiveId}
          selectedIds={selectedIds}
          onToggleSelect={toggleSelect}
          onToggleSelectMany={toggleSelectMany}
        />
      )}

      {selectedIds.size > 0 && (
        <BulkActionBar
          count={selectedIds.size}
          onClose={() => setConfirmBulkClose(true)}
          onClear={clearSelection}
        />
      )}
      {confirmBulkClose && (
        <BulkCloseConfirmModal
          count={selectedIds.size}
          submitting={bulkClosing}
          onCancel={() => setConfirmBulkClose(false)}
          onConfirm={handleBulkClose}
        />
      )}

      {createOpen && (
        <CreateTicketModal team={team} onClose={() => setCreateOpen(false)} onSubmit={handleCreate} />
      )}
      {activeTicket && (
        <TicketDetailModal
          key={activeTicket.id}
          ticket={activeTicket}
          team={team}
          onClose={() => setActiveId(null)}
          onUpdate={updateTicket}
          onRefresh={load}
        />
      )}
    </div>
  );
}

// -------------------- Subcomponents --------------------

function StatPill({ label, value, tone, icon: Icon, testid }) {
  const toneCls = {
    slate: "bg-slate-100 border-slate-200 text-slate-800",
    rose: "bg-rose-100 border-rose-200 text-rose-900",
    emerald: "bg-emerald-100 border-emerald-200 text-emerald-900",
    sky: "bg-sky-100 border-sky-200 text-sky-900",
  }[tone || "slate"];
  return (
    <div
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 border rounded-full text-xs font-semibold whitespace-nowrap ${toneCls}`}
      data-testid={testid}
    >
      {Icon && <Icon className="w-3.5 h-3.5" />}
      <span className="opacity-75">{label}</span>
      <span className="text-sm font-bold">{value}</span>
    </div>
  );
}

function Select({ value, onChange, placeholder, options, testid }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      data-testid={testid}
      className="text-sm border border-[var(--ayci-border)] rounded-md px-2.5 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-[var(--ayci-accent)]/40"
    >
      <option value="">{placeholder}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function PriorityChip({ priority }) {
  const meta = PRIORITY_META[priority] || PRIORITY_META.medium;
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 text-[10px] uppercase tracking-wider font-bold rounded border ${meta.chip}`}
      data-testid={`ticket-priority-chip-${priority}`}
    >
      {meta.label}
    </span>
  );
}

function StatusChip({ status }) {
  const meta = STATUS_META[status] || STATUS_META.open;
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 text-[11px] font-semibold rounded border ${meta.chip}`}
      data-testid={`ticket-status-chip-${status}`}
    >
      {meta.label}
    </span>
  );
}

// Compact "Tier · Cohort · Interview date" stripe rendered under the student
// name on Kanban cards and table rows so coaches see at-a-glance whether a
// ticket is from a private-tier student with an imminent interview.
function shortenTier(tier) {
  if (!tier) return null;
  return tier.replace(/^Academy\s+/i, "").replace(/Private\s+Plus/i, "Private+");
}

function parseInterviewDate(raw) {
  if (!raw) return null;
  const d = new Date(raw);
  if (isNaN(d.getTime())) return null;
  d.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diffDays = Math.round((d - today) / 86400000);
  const label = d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  let tone, suffix;
  if (diffDays < 0) {
    tone = "bg-slate-100 text-slate-600 border-slate-200";
    suffix = `${Math.abs(diffDays)}d ago`;
  } else if (diffDays === 0) {
    tone = "bg-rose-100 text-rose-800 border-rose-300";
    suffix = "today";
  } else if (diffDays <= 7) {
    tone = "bg-rose-50 text-rose-800 border-rose-200";
    suffix = `in ${diffDays}d`;
  } else if (diffDays <= 21) {
    tone = "bg-amber-50 text-amber-900 border-amber-200";
    suffix = `in ${diffDays}d`;
  } else {
    tone = "bg-emerald-50 text-emerald-800 border-emerald-200";
    suffix = `in ${diffDays}d`;
  }
  return { label, suffix, tone, diffDays };
}

function StudentMatchStripe({ match, compact = false }) {
  if (!match || !match.matched) return null;
  const tier = shortenTier(match.tier);
  const cohort = match.cohort;
  const iv = parseInterviewDate(match.interview_date);
  if (!tier && !cohort && !iv) return null;
  return (
    <div
      className={`mt-1 flex items-center gap-1 flex-wrap ${compact ? "text-[10px]" : "text-[10.5px]"}`}
      data-testid="ticket-student-stripe"
    >
      {tier && (
        <span className="inline-flex items-center px-1.5 py-px rounded border bg-violet-50 text-violet-800 border-violet-200 font-semibold leading-tight">
          {tier}
        </span>
      )}
      {cohort && (
        <span className="inline-flex items-center px-1.5 py-px rounded border bg-slate-50 text-slate-700 border-slate-200 leading-tight">
          {cohort}
        </span>
      )}
      {iv && (
        <span
          className={`inline-flex items-center gap-0.5 px-1.5 py-px rounded border font-semibold leading-tight ${iv.tone}`}
          title={`Interview ${iv.label} — ${iv.suffix}`}
        >
          <Calendar className="w-2.5 h-2.5" />
          {iv.label}
          <span className="opacity-70 font-normal ml-0.5">· {iv.suffix}</span>
        </span>
      )}
    </div>
  );
}



function KanbanBoard({ grouped, teamById, onOpen, onUpdate, selectedIds, onToggleSelect, onToggleSelectMany }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-3" data-testid="tickets-kanban">
      {STATUSES.map((s) => {
        const colTickets = grouped[s.value];
        const colIds = colTickets.map((t) => t.id);
        const selectedInCol = colIds.filter((id) => selectedIds.has(id)).length;
        const allSelected = colIds.length > 0 && selectedInCol === colIds.length;
        const someSelected = selectedInCol > 0 && !allSelected;
        return (
          <div key={s.value} className="bg-slate-50 border border-slate-200 rounded-lg flex flex-col min-h-[300px]">
            <div className={`px-3 py-2 border-b border-slate-200 flex items-center justify-between rounded-t-lg ${s.chip}`}>
              <div className="flex items-center gap-2">
                {colIds.length > 0 && (
                  <input
                    type="checkbox"
                    aria-label={`Select all ${s.label}`}
                    checked={allSelected}
                    ref={(el) => { if (el) el.indeterminate = someSelected; }}
                    onChange={(e) => onToggleSelectMany(colIds, e.target.checked)}
                    onClick={(e) => e.stopPropagation()}
                    className="w-3.5 h-3.5 rounded border-slate-400 text-[var(--ayci-accent)] focus:ring-1 focus:ring-[var(--ayci-accent)] cursor-pointer"
                    data-testid={`tickets-kanban-select-all-${s.value}`}
                  />
                )}
                <span className="text-xs font-semibold uppercase tracking-wider">{s.label}</span>
              </div>
              <span className="text-xs font-bold">{colTickets.length}</span>
            </div>
            <div className="p-2 space-y-2 flex-1 overflow-y-auto max-h-[70vh]">
              {colTickets.length === 0 ? (
                <div className="text-center text-xs text-slate-400 py-6">—</div>
              ) : (
                colTickets.map((t) => (
                  <KanbanCard
                    key={t.id}
                    ticket={t}
                    teamById={teamById}
                    onOpen={() => onOpen(t.id)}
                    onUpdate={onUpdate}
                    selected={selectedIds.has(t.id)}
                    onToggleSelect={() => onToggleSelect(t.id)}
                  />
                ))
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function KanbanCard({ ticket, teamById, onOpen, onUpdate, selected, onToggleSelect }) {
  const assignee = ticket.assignee_id ? teamById[ticket.assignee_id] : null;
  const unread = !!ticket.unread;
  const circleUnread = (ticket.unread_circle_count || 0) > 0;
  return (
    <div
      onClick={onOpen}
      className={[
        "bg-white border rounded-md p-2.5 cursor-pointer hover:shadow-md transition-shadow text-sm group relative",
        selected
          ? "border-[var(--ayci-accent)] ring-2 ring-[var(--ayci-accent)]/40 shadow-sm"
          : circleUnread
            ? "border-violet-400 ring-2 ring-violet-200/70 shadow-sm"
            : unread
              ? "border-rose-400 ring-2 ring-rose-200/70 shadow-sm"
              : ticket.overdue
              ? "border-rose-300 ring-1 ring-rose-200"
              : "border-slate-200",
      ].join(" ")}
      data-testid={`ticket-card-${ticket.id}`}
    >
      <div
        className="absolute top-2 left-2 z-10"
        onClick={(e) => { e.stopPropagation(); onToggleSelect(); }}
      >
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggleSelect}
          onClick={(e) => e.stopPropagation()}
          aria-label={`Select ticket ${ticket.subject}`}
          className="w-3.5 h-3.5 rounded border-slate-300 text-[var(--ayci-accent)] focus:ring-1 focus:ring-[var(--ayci-accent)] cursor-pointer"
          data-testid={`ticket-card-select-${ticket.id}`}
        />
      </div>
      {unread && (
        <span
          className="absolute -top-1 -right-1 flex items-center"
          title="New activity since you last opened this ticket"
          data-testid="ticket-unread-badge"
        >
          <span className="absolute inline-flex h-3 w-3 rounded-full bg-rose-500 opacity-60 animate-ping" />
          <span className="relative inline-flex h-3 w-3 rounded-full bg-rose-600 ring-2 ring-white" />
        </span>
      )}
      <div className="flex items-start justify-between gap-2 mb-1.5 pl-5">
        <div className="flex items-center gap-1.5">
          <PriorityChip priority={ticket.priority} />
          {unread && (
            <span className="inline-flex items-center text-[9px] font-bold text-rose-700 bg-rose-100 border border-rose-300 px-1.5 py-0.5 rounded uppercase tracking-wider">
              New
            </span>
          )}
          {circleUnread && (
            <span
              className="inline-flex items-center gap-0.5 text-[9px] font-bold text-violet-700 bg-violet-100 border border-violet-300 px-1.5 py-0.5 rounded uppercase tracking-wider"
              title={`${ticket.unread_circle_count} new Circle DM ${ticket.unread_circle_count === 1 ? "reply" : "replies"} — last ${relativeAge(ticket.last_circle_activity_at)}`}
              data-testid={`ticket-circle-unread-${ticket.id}`}
            >
              <MessageCircle className="w-2.5 h-2.5" />
              {ticket.unread_circle_count} new
            </span>
          )}
        </div>
        {ticket.overdue && (
          <span className="inline-flex items-center gap-0.5 text-[10px] font-bold text-rose-700">
            <AlertTriangle className="w-3 h-3" /> SLA
          </span>
        )}
      </div>
      <div
        className={`line-clamp-2 leading-snug ${unread ? "font-bold text-[var(--ayci-ink)]" : "font-semibold text-[var(--ayci-ink)]"}`}
      >
        {ticket.subject}
      </div>
      <div className="text-xs text-[var(--ayci-ink-muted)] mt-1 truncate">{ticket.student_name}</div>
      <StudentMatchStripe match={ticket.student_match} compact />
      <div className="text-[11px] text-[var(--ayci-ink-muted)] mt-1.5 flex items-center justify-between gap-1">
        <span className="flex items-center gap-1">
          <Clock className="w-3 h-3" />
          {relativeAge(ticket.updated_at || ticket.created_at)}
          {(() => {
            // `attachments_count` is sent by the list endpoint (lightweight).
            // Fall back to the full `attachments` array length for the
            // detail-modal path that hydrates the full ticket shape.
            const n = ticket.attachments_count ?? (ticket.attachments || []).length;
            if (!n) return null;
            return (
              <span className="ml-1 inline-flex items-center gap-0.5 text-slate-600" title={`${n} attachment(s)`}>
                <Paperclip className="w-3 h-3" />
                {n}
              </span>
            );
          })()}
        </span>
        {assignee ? (
          <span className="px-1.5 py-0.5 rounded bg-sky-100 text-sky-800 truncate max-w-[100px]">
            {assignee.name}
          </span>
        ) : (
          <span className="text-amber-700">unassigned</span>
        )}
      </div>
    </div>
  );
}

function TicketTable({ rows, teamById, onOpen, selectedIds, onToggleSelect, onToggleSelectMany }) {
  if (rows.length === 0) {
    return (
      <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-12 text-center text-sm text-[var(--ayci-ink-muted)]">
        No tickets match the current filters.
      </div>
    );
  }
  const visibleIds = rows.map((r) => r.id);
  const selectedVisible = visibleIds.filter((id) => selectedIds.has(id)).length;
  const allChecked = selectedVisible === visibleIds.length;
  const someChecked = selectedVisible > 0 && !allChecked;
  return (
    <div className="bg-white border border-[var(--ayci-border)] rounded-lg overflow-hidden" data-testid="tickets-table">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-[11px] uppercase tracking-wider text-[var(--ayci-ink-muted)] font-semibold">
            <tr>
              <th className="px-3 py-2.5 w-8">
                <input
                  type="checkbox"
                  aria-label="Select all visible"
                  checked={allChecked}
                  ref={(el) => { if (el) el.indeterminate = someChecked; }}
                  onChange={(e) => onToggleSelectMany(visibleIds, e.target.checked)}
                  className="w-3.5 h-3.5 rounded border-slate-400 text-[var(--ayci-accent)] focus:ring-1 focus:ring-[var(--ayci-accent)] cursor-pointer"
                  data-testid="tickets-table-select-all"
                />
              </th>
              <th className="text-left px-3 py-2.5">Priority</th>
              <th className="text-left px-3 py-2.5">Status</th>
              <th className="text-left px-3 py-2.5">Subject</th>
              <th className="text-left px-3 py-2.5">Student</th>
              <th className="text-left px-3 py-2.5">Category</th>
              <th className="text-left px-3 py-2.5">Assignee</th>
              <th className="text-left px-3 py-2.5">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((t) => {
              const assignee = t.assignee_id ? teamById[t.assignee_id] : null;
              const isSelected = selectedIds.has(t.id);
              return (
                <tr
                  key={t.id}
                  onClick={() => onOpen(t.id)}
                  className={[
                    "hover:bg-slate-50 cursor-pointer",
                    isSelected ? "bg-[var(--ayci-accent)]/5" : t.overdue ? "bg-rose-50/40" : "",
                  ].join(" ")}
                  data-testid={`ticket-row-${t.id}`}
                >
                  <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => onToggleSelect(t.id)}
                      aria-label={`Select ticket ${t.subject}`}
                      className="w-3.5 h-3.5 rounded border-slate-300 text-[var(--ayci-accent)] focus:ring-1 focus:ring-[var(--ayci-accent)] cursor-pointer"
                      data-testid={`ticket-row-select-${t.id}`}
                    />
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-1.5">
                      <PriorityChip priority={t.priority} />
                      {t.overdue && <AlertTriangle className="w-3.5 h-3.5 text-rose-600" />}
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <StatusChip status={t.status} />
                  </td>
                  <td className="px-3 py-2.5 max-w-md">
                    <div className="font-semibold text-[var(--ayci-ink)] truncate">{t.subject}</div>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="text-[var(--ayci-ink)]">{t.student_name}</div>
                    <div className="text-xs text-[var(--ayci-ink-muted)]">{t.student_email}</div>
                    <StudentMatchStripe match={t.student_match} />
                  </td>
                  <td className="px-3 py-2.5 capitalize text-[var(--ayci-ink-muted)]">{t.category}</td>
                  <td className="px-3 py-2.5 text-[var(--ayci-ink-muted)]">
                    {assignee ? assignee.name : <span className="text-amber-700">unassigned</span>}
                  </td>
                  <td className="px-3 py-2.5 text-[var(--ayci-ink-muted)] whitespace-nowrap">
                    {formatUk(t.created_at)}
                    <div className="text-[11px] opacity-70">{relativeAge(t.created_at)}</div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BulkActionBar({ count, onClose, onClear }) {
  return (
    <div
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 bg-[var(--ayci-ink)] text-white rounded-full shadow-lg shadow-slate-900/30 pl-5 pr-2 py-2 flex items-center gap-3 animate-in fade-in slide-in-from-bottom-4"
      data-testid="tickets-bulk-action-bar"
    >
      <span className="text-sm font-semibold" data-testid="tickets-bulk-count">
        {count} selected
      </span>
      <span className="h-5 w-px bg-white/20" />
      <button
        onClick={onClose}
        className="text-xs font-semibold inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-rose-500 hover:bg-rose-600 transition-colors"
        data-testid="tickets-bulk-close-button"
      >
        <XCircle className="w-3.5 h-3.5" /> Close tickets
      </button>
      <button
        onClick={onClear}
        className="text-xs font-medium px-3 py-1.5 rounded-full text-white/80 hover:text-white hover:bg-white/10 transition-colors"
        data-testid="tickets-bulk-clear"
      >
        Clear
      </button>
    </div>
  );
}

function BulkCloseConfirmModal({ count, submitting, onCancel, onConfirm }) {
  return (
    <div
      className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4"
      onClick={onCancel}
      data-testid="tickets-bulk-confirm-modal"
    >
      <div
        className="bg-white rounded-lg shadow-xl max-w-sm w-full p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="font-display text-lg font-bold text-[var(--ayci-ink)] mb-1">
          Close {count} ticket{count === 1 ? "" : "s"}?
        </h3>
        <p className="text-sm text-[var(--ayci-ink-muted)] mb-4">
          Selected tickets will be marked <strong>closed</strong> and removed
          from active queues. This won't notify the students.
        </p>
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={onCancel}
            disabled={submitting}
            data-testid="tickets-bulk-confirm-cancel"
          >
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={onConfirm}
            disabled={submitting}
            className="bg-rose-600 hover:bg-rose-700 text-white"
            data-testid="tickets-bulk-confirm-submit"
          >
            {submitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> Closing…
              </>
            ) : (
              <>
                <XCircle className="w-4 h-4 mr-1.5" /> Close {count}
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}

function CreateTicketModal({ team, onClose, onSubmit }) {
  const [form, setForm] = useState({
    student_name: "",
    student_email: "",
    subject: "",
    description: "",
    priority: "medium",
    category: "other",
    assignee_id: "",
  });
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.student_email || !form.subject || !form.student_name) {
      toast.error("Name, email and subject are required");
      return;
    }
    setSubmitting(true);
    await onSubmit({
      ...form,
      assignee_id: form.assignee_id || null,
    });
    setSubmitting(false);
  };

  return (
    <Modal title="New ticket" onClose={onClose} testid="ticket-create-modal">
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Student name" required>
            <input
              type="text"
              value={form.student_name}
              onChange={(e) => setForm({ ...form, student_name: e.target.value })}
              required
              data-testid="ticket-create-name"
              className={inputCls}
            />
          </Field>
          <Field label="Student email" required>
            <input
              type="email"
              value={form.student_email}
              onChange={(e) => setForm({ ...form, student_email: e.target.value })}
              required
              data-testid="ticket-create-email"
              className={inputCls}
            />
          </Field>
        </div>
        <Field label="Subject" required>
          <input
            type="text"
            value={form.subject}
            onChange={(e) => setForm({ ...form, subject: e.target.value })}
            required
            data-testid="ticket-create-subject"
            className={inputCls}
          />
        </Field>
        <Field label="Description">
          <textarea
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            rows={4}
            data-testid="ticket-create-description"
            className={inputCls}
          />
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Priority">
            <select
              value={form.priority}
              onChange={(e) => setForm({ ...form, priority: e.target.value })}
              data-testid="ticket-create-priority"
              className={inputCls}
            >
              {PRIORITIES.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Category">
            <select
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
              data-testid="ticket-create-category"
              className={inputCls}
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Assignee">
            <select
              value={form.assignee_id}
              onChange={(e) => setForm({ ...form, assignee_id: e.target.value })}
              data-testid="ticket-create-assignee"
              className={inputCls}
            >
              <option value="">Unassigned</option>
              {team.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="flex justify-end gap-2 pt-2 border-t border-slate-100">
          <Button type="button" variant="outline" onClick={onClose} data-testid="ticket-create-cancel">
            Cancel
          </Button>
          <Button type="submit" disabled={submitting} data-testid="ticket-create-submit">
            {submitting && <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />}
            Create ticket
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function TicketDetailModal({ ticket, team, onClose, onUpdate, onRefresh }) {
  const [note, setNote] = useState("");
  const [posting, setPosting] = useState(false);
  const [fullTicket, setFullTicket] = useState(ticket);
  const [matching, setMatching] = useState(false);

  // Re-fetch the full ticket whenever the parent's ticket reference updates
  // (covers: open, after PATCH/note add, after onRefresh from reply panels).
  // Without this, local state goes stale and changes appear to "not save".
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await apiClient.get(`/tickets/${ticket.id}`);
        if (!cancelled) setFullTicket(data);
      } catch {
        if (!cancelled) setFullTicket(ticket);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ticket.id, ticket.updated_at, ticket.assignee_id, ticket.status, ticket.priority, ticket.category, (ticket.notes || []).length]);

  const t = fullTicket || ticket;

  const handleField = async (field, value) => {
    // Optimistically reflect the change locally so the dropdown doesn't snap
    // back while the server PATCH is in flight.
    setFullTicket((prev) => (prev ? { ...prev, [field]: value } : prev));
    const updated = await onUpdate(ticket.id, { [field]: value });
    if (updated) {
      setFullTicket((prev) => ({ ...(prev || {}), ...updated }));
      // Make status transitions obvious — the card moves out of the Open
      // column into Resolved/Closed (which is often off-screen on narrow
      // viewports), so without feedback users think the change didn't save.
      if (field === "status") {
        const LABEL = {
          open: "Open",
          in_progress: "In Progress",
          waiting: "Waiting on Student",
          resolved: "Resolved",
          closed: "Closed",
        };
        toast.success(`Ticket marked ${LABEL[value] || value}`);
        if (value === "closed" || value === "resolved") {
          // Give the toast a moment to appear, then close the modal and
          // refresh the parent list so the Kanban columns reflect the move.
          setTimeout(() => {
            onRefresh();
            onClose();
          }, 300);
        }
      }
    }
  };

  const handleAddNote = async () => {
    const body = note.trim();
    if (!body) return;
    setPosting(true);
    try {
      await apiClient.post(`/tickets/${ticket.id}/notes`, { body, internal: true });
      setNote("");
      // Optimistically refetch THIS ticket so the new note appears immediately
      try {
        const { data } = await apiClient.get(`/tickets/${ticket.id}`);
        setFullTicket(data);
      } catch {
        // ignore — onRefresh will catch us up
      }
      onRefresh();
      toast.success("Internal note saved");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to save note");
    } finally {
      setPosting(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm("Delete this ticket? This cannot be undone.")) return;
    try {
      await apiClient.delete(`/tickets/${ticket.id}`);
      await onRefresh();
      onClose();
      toast.success("Ticket deleted");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to delete");
    }
  };

  const match = t.student_match;
  const matchedEmail = (match && match.matched && match.email) || t.student_email || null;
  const studentLookupHref = matchedEmail
    ? `/students?email=${encodeURIComponent(matchedEmail)}`
    : t.student_name
    ? `/students?name=${encodeURIComponent(t.student_name)}`
    : null;

  return (
    <Modal title={null} onClose={onClose} wide testid="ticket-detail-modal">
      <div className="space-y-4">
        <div className="flex items-start gap-3">
          <PriorityChip priority={t.priority} />
          <StatusChip status={t.status} />
          {t.overdue && (
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-700 bg-rose-50 border border-rose-200 px-2 py-0.5 rounded">
              <AlertTriangle className="w-3 h-3" /> SLA breach
            </span>
          )}
          <span className="ml-auto text-[11px] uppercase tracking-wider text-[var(--ayci-ink-muted)]">
            via {SOURCE_LABEL[t.source] || t.source}
          </span>
        </div>
        <h2 className="text-xl font-bold text-[var(--ayci-ink)] font-display leading-tight">
          {t.subject}
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <Label>Student</Label>
            <div className="font-semibold">{t.student_name}</div>
            {t.student_email && (
              <a
                href={`mailto:${t.student_email}`}
                className="text-sm text-[var(--ayci-accent)] hover:underline flex items-center gap-1 mt-0.5"
              >
                <Mail className="w-3 h-3" /> {t.student_email}
              </a>
            )}
            {t.wati_wa_id && (
              <div className="text-sm text-emerald-700 flex items-center gap-1 mt-0.5">
                <MessageCircle className="w-3 h-3" /> {t.wati_wa_id}
              </div>
            )}

            {match && match.matched ? (
              <div
                className="mt-2 border border-emerald-200 bg-emerald-50 rounded-md p-2 text-xs"
                data-testid="linked-student-card"
              >
                <div className="text-[10px] uppercase tracking-wider font-bold text-emerald-800 mb-0.5">
                  Linked student record
                </div>
                <div className="font-semibold text-[var(--ayci-ink)]">{match.name}</div>
                <div className="flex flex-wrap gap-1 mt-1">
                  {match.tier && (
                    <span className="bg-white border border-slate-200 px-1.5 py-0.5 rounded text-[10px]">
                      {match.tier}
                    </span>
                  )}
                  {match.cohort && (
                    <span className="bg-white border border-slate-200 px-1.5 py-0.5 rounded text-[10px]">
                      {match.cohort}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-3 mt-1.5">
                  {studentLookupHref && (
                    <a
                      href={studentLookupHref}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[var(--ayci-accent)] hover:underline flex items-center gap-1 font-semibold"
                      data-testid="ticket-student-lookup-link"
                    >
                      <ExternalLink className="w-3 h-3" /> Student Lookup
                    </a>
                  )}
                  {match.monday_url && (
                    <a
                      href={match.monday_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-accent)] flex items-center gap-1"
                    >
                      <ExternalLink className="w-3 h-3" /> Monday
                    </a>
                  )}
                </div>
              </div>
            ) : (
              <div className="mt-2 text-[11px] text-[var(--ayci-ink-muted)] italic">
                Not matched to a student record yet —
                <button
                  onClick={async () => {
                    setMatching(true);
                    try {
                      const { data } = await apiClient.post(`/tickets/${t.id}/match-student`);
                      setFullTicket({ ...t, student_match: data });
                      if (data.matched) toast.success(`Linked: ${data.name}`);
                      else toast.info("No matching student found in Monday");
                    } catch (err) {
                      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Match failed");
                    } finally {
                      setMatching(false);
                    }
                  }}
                  disabled={matching}
                  className="ml-1 text-[var(--ayci-accent)] hover:underline font-semibold"
                  data-testid="ticket-match-student-retry"
                >
                  {matching ? "searching…" : "search again"}
                </button>
                {studentLookupHref && (
                  <>
                    {" · "}
                    <a
                      href={studentLookupHref}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[var(--ayci-accent)] hover:underline font-semibold inline-flex items-center gap-1 not-italic"
                      data-testid="ticket-student-lookup-fallback"
                    >
                      <ExternalLink className="w-3 h-3" /> open Student Lookup
                    </a>
                  </>
                )}
              </div>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <Field label="Status">
              <select
                value={t.status}
                onChange={(e) => handleField("status", e.target.value)}
                data-testid="ticket-detail-status"
                className={inputCls}
              >
                {STATUSES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Priority">
              <select
                value={t.priority}
                onChange={(e) => handleField("priority", e.target.value)}
                data-testid="ticket-detail-priority"
                className={inputCls}
              >
                {PRIORITIES.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Category">
              <select
                value={t.category}
                onChange={(e) => handleField("category", e.target.value)}
                data-testid="ticket-detail-category"
                className={inputCls}
              >
                {CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Assignee">
              <select
                value={t.assignee_id || ""}
                onChange={(e) => handleField("assignee_id", e.target.value || null)}
                data-testid="ticket-detail-assignee"
                className={inputCls}
              >
                <option value="">Unassigned</option>
                {team.map((tm) => (
                  <option key={tm.id} value={tm.id}>
                    {tm.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </div>
        {/* Conversation thread — newest first so the latest reply is the
            first thing the team sees. The original message is shown last. */}
        <ConversationThread ticket={t} onRefresh={async () => {
          try {
            const { data } = await apiClient.get(`/tickets/${ticket.id}`);
            setFullTicket(data);
          } catch {
            // ignore
          }
          onRefresh();
        }} />

        {t.source === "whatsapp" && (
          <WhatsAppReplyPanel ticket={t} onSent={onRefresh} />
        )}

        {t.source === "circle_dm" && (
          <CircleReplyPanel ticket={t} onSent={onRefresh} />
        )}

        {t.student_email && t.source !== "whatsapp" && t.source !== "circle_dm" && (
          <EmailReplyPanel ticket={t} onSent={onRefresh} />
        )}

        <div className="bg-amber-50/40 border border-amber-200 rounded-lg p-3">
          {(() => {
            // Only show genuinely-internal notes here. Inbound replies from
            // WhatsApp / Gmail and outbound replies are already rendered in
            // the ConversationThread above.
            const nonReplyAuthorIds = new Set([
              "_whatsapp", "_whatsapp_outbound",
              "_gmail", "_gmail_outbound",
              "_circle_dm", "_circle_dm_outbound",
            ]);
            const teamNotes = (t.notes || []).filter(
              (n) => !nonReplyAuthorIds.has(n.author_id),
            );
            return (
              <>
                <div className="flex items-center gap-2 mb-2">
                  <Lock className="w-3.5 h-3.5 text-amber-700" />
                  <Label className="text-amber-900 mb-0">
                    Internal notes ({teamNotes.length})
                  </Label>
                  <span className="text-[10px] uppercase tracking-wider text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded font-bold">
                    Team only · never sent to student
                  </span>
                </div>
                <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
                  {teamNotes.length === 0 ? (
                    <div className="text-xs text-[var(--ayci-ink-muted)] italic">No internal notes yet.</div>
                  ) : (
                    teamNotes.map((n) => (
                <div
                  key={n.id}
                  className="border border-amber-200 bg-white rounded-md p-2.5 text-sm"
                  data-testid={`ticket-note-${n.id}`}
                >
                  <div className="flex items-center justify-between text-[11px] text-[var(--ayci-ink-muted)] mb-1">
                    <span className="font-semibold text-[var(--ayci-ink)] flex items-center gap-1">
                      <Lock className="w-3 h-3 text-amber-600" />
                      {n.author_name}
                    </span>
                    <span>{formatUk(n.created_at)}</span>
                  </div>
                  <div className="whitespace-pre-wrap">{n.body}</div>
                  <AttachmentList ticketId={t.id} attachments={n.attachments} compact />
                </div>
                    ))
                  )}
                </div>
          <div className="flex items-end gap-2 mt-3">
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Write an internal note for the team — not sent to the student"
              rows={2}
              className={inputCls + " bg-white"}
              data-testid="ticket-add-note-input"
            />
            <Button
              onClick={handleAddNote}
              disabled={!note.trim() || posting}
              size="sm"
              variant="outline"
              className="border-amber-400 text-amber-900 hover:bg-amber-100"
              data-testid="ticket-add-note-submit"
            >
              {posting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <>
                  <Lock className="w-3.5 h-3.5 mr-1" />
                  Save note
                </>
              )}
            </Button>
          </div>
              </>
            );
          })()}
        </div>

        <div className="flex justify-between items-center pt-3 border-t border-slate-100 text-[11px] text-[var(--ayci-ink-muted)]">
          <div>
            Created {formatUk(t.created_at)} ·{" "}
            {t.resolved_at ? `Resolved ${formatUk(t.resolved_at)}` : `Updated ${formatUk(t.updated_at)}`}
          </div>
          <button
            onClick={handleDelete}
            className="text-rose-600 hover:text-rose-800 font-semibold uppercase tracking-wider"
            data-testid="ticket-delete-button"
          >
            Delete
          </button>
        </div>
      </div>
    </Modal>
  );
}

// -------------------- Conversation thread (newest-first) --------------------

const STUDENT_AUTHOR_IDS = new Set(["_whatsapp", "_gmail", "_circle_dm"]);
const TEAM_OUTBOUND_AUTHOR_IDS = new Set(["_whatsapp_outbound", "_gmail_outbound", "_circle_dm_outbound"]);

// Renders the entire ticket conversation (original message + every reply +
// outbound replies from the team) in a chat-style timeline. The most recent
// message is at the TOP — that's the whole point: the team always sees the
// freshest student reply first, no scrolling required.
function ConversationThread({ ticket, onRefresh }) {
  const [deletingId, setDeletingId] = useState(null);

  const handleDelete = async (noteId) => {
    if (!noteId || noteId.startsWith("__desc__")) return;
    if (!window.confirm("Delete this message? It can't be undone.")) return;
    setDeletingId(noteId);
    try {
      await apiClient.delete(`/tickets/${ticket.id}/notes/${noteId}`);
      toast.success("Message deleted");
      onRefresh?.();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Delete failed");
    } finally {
      setDeletingId(null);
    }
  };

  const items = [];

  // Original incoming ticket body — modelled as the first message
  if (ticket.description) {
    items.push({
      kind: "student",
      author: ticket.student_name || "Student",
      body: ticket.description,
      created_at: ticket.created_at,
      attachments: ticket.attachments || [],
      id: `__desc__${ticket.id}`,
    });
  }

  for (const n of ticket.notes || []) {
    let kind = "team-internal";
    if (STUDENT_AUTHOR_IDS.has(n.author_id)) kind = "student";
    else if (TEAM_OUTBOUND_AUTHOR_IDS.has(n.author_id)) kind = "team-reply";
    if (kind === "team-internal") continue; // shown in the amber Internal Notes panel
    items.push({
      kind,
      author: n.author_name,
      body: n.body,
      created_at: n.created_at,
      attachments: n.attachments || [],
      id: n.id,
    });
  }

  // Newest first
  items.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));

  if (items.length === 0) {
    return (
      <div className="text-sm text-[var(--ayci-ink-muted)] italic">No messages yet.</div>
    );
  }

  const latestStudentIdx = items.findIndex((i) => i.kind === "student");

  return (
    <div data-testid="conversation-thread">
      <Label>Conversation ({items.length}) — newest first</Label>
      <div className="space-y-2">
        {items.map((m, i) => {
          const isStudent = m.kind === "student";
          const isLatestStudent = i === latestStudentIdx;
          const tone = isStudent
            ? isLatestStudent
              ? "bg-rose-50 border-rose-300 ring-2 ring-rose-200"
              : "bg-rose-50 border-rose-200"
            : "bg-emerald-50 border-emerald-200";
          return (
            <div
              key={m.id}
              className={`border rounded-md p-3 text-sm ${tone}`}
              data-testid={`thread-message-${m.id}`}
            >
              <div className="flex items-center justify-between text-[11px] text-[var(--ayci-ink-muted)] mb-1.5">
                <span className="font-semibold text-[var(--ayci-ink)] flex items-center gap-1.5">
                  {isStudent ? (
                    <span className="inline-flex items-center gap-1 text-rose-700">
                      <MessageCircle className="w-3.5 h-3.5" />
                      {m.author}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-emerald-700">
                      <Send className="w-3.5 h-3.5" />
                      {m.author}
                    </span>
                  )}
                  {isLatestStudent && (
                    <span className="text-[9px] font-bold uppercase tracking-wider text-rose-700 bg-rose-200 px-1.5 py-0.5 rounded">
                      Latest from student
                    </span>
                  )}
                </span>
                <span className="flex items-center gap-2">
                  <span>{formatUk(m.created_at)}</span>
                  {!m.id?.startsWith("__desc__") && (
                    <button
                      onClick={() => handleDelete(m.id)}
                      disabled={deletingId === m.id}
                      title="Delete this message (e.g. duplicate)"
                      className="text-slate-400 hover:text-rose-600 disabled:opacity-40"
                      data-testid={`thread-delete-${m.id}`}
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
                </span>
              </div>
              <div className="whitespace-pre-wrap text-[var(--ayci-ink)]">{m.body}</div>
              <AttachmentList ticketId={ticket.id} attachments={m.attachments} compact />
            </div>
          );
        })}
      </div>
    </div>
  );
}



// -------------------- Email reply panel (Gmail two-way) --------------------

function EmailReplyPanel({ ticket, onSent }) {
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [inboxes, setInboxes] = useState([]);
  const [selectedInbox, setSelectedInbox] = useState("");
  const [loadingInboxes, setLoadingInboxes] = useState(false);
  const [gmailReady, setGmailReady] = useState(null); // null=unknown

  const originalInbox = ticket.gmail_inbox_email;
  const needsPicker = !originalInbox; // non-email tickets need to choose

  // Load gmail status + inboxes once
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoadingInboxes(true);
      try {
        const { data } = await apiClient.get("/oauth/gmail/status");
        if (cancelled) return;
        setGmailReady(!!data.configured);
        setInboxes(data.inboxes || []);
        if (!originalInbox && (data.inboxes || []).length > 0) {
          setSelectedInbox(data.inboxes[0].email);
        }
      } catch {
        setGmailReady(false);
      } finally {
        if (!cancelled) setLoadingInboxes(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [originalInbox]);

  const handleSend = async () => {
    const text = body.trim();
    if (!text) return;
    setSending(true);
    try {
      const { data } = await apiClient.post(`/oauth/gmail/tickets/${ticket.id}/reply`, {
        body: text,
        from_inbox_email: originalInbox ? undefined : selectedInbox || undefined,
      });
      setBody("");
      toast.success(`Reply sent from ${data.from_inbox || originalInbox}`);
      onSent && (await onSent());
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Send failed");
    } finally {
      setSending(false);
    }
  };

  if (loadingInboxes) {
    return (
      <div className="border border-slate-200 bg-slate-50 rounded-md p-3 text-xs text-[var(--ayci-ink-muted)] flex items-center gap-2">
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Checking Gmail…
      </div>
    );
  }

  if (!gmailReady) {
    return (
      <div className="border border-amber-200 bg-amber-50 rounded-md p-3 text-xs text-amber-900">
        Gmail integration not configured yet. Admin must connect a Gmail inbox in Settings → Inboxes to enable email replies.
      </div>
    );
  }

  if (!originalInbox && inboxes.length === 0) {
    return (
      <div className="border border-amber-200 bg-amber-50 rounded-md p-3 text-xs text-amber-900">
        No Gmail inbox connected yet. Connect one in Settings → Inboxes to reply from the dashboard.
      </div>
    );
  }

  const fromLabel = originalInbox
    ? `from ${originalInbox}`
    : `from ${selectedInbox || "(choose inbox)"}`;

  return (
    <div
      className="border border-sky-200 bg-sky-50/40 rounded-md p-3"
      data-testid="email-reply-panel"
    >
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <Mail className="w-4 h-4 text-sky-700" />
        <span className="text-[11px] uppercase tracking-wider font-semibold text-sky-800">
          Reply via Gmail · {fromLabel} · to {ticket.student_email}
        </span>
      </div>
      {needsPicker && inboxes.length > 1 && (
        <select
          value={selectedInbox}
          onChange={(e) => setSelectedInbox(e.target.value)}
          className={inputCls + " mb-2"}
          data-testid="email-reply-inbox-picker"
        >
          {inboxes.map((ib) => (
            <option key={ib.id} value={ib.email}>
              {ib.email}
            </option>
          ))}
        </select>
      )}
      <div className="flex items-end gap-2">
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Type a reply…"
          rows={4}
          className={inputCls}
          data-testid="email-reply-input"
        />
        <Button
          onClick={handleSend}
          disabled={!body.trim() || sending}
          size="sm"
          data-testid="email-reply-send"
          className="bg-sky-600 hover:bg-sky-700"
        >
          {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
        </Button>
      </div>
    </div>
  );
}




// -------------------- WhatsApp reply panel --------------------


// -------------------- Attachments --------------------

function AttachmentList({ ticketId, attachments, compact }) {
  const list = attachments || [];
  if (list.length === 0) return null;
  return (
    <div
      className={`flex flex-wrap gap-2 ${compact ? "mt-1.5" : "mt-2"}`}
      data-testid="ticket-attachments"
    >
      {list.map((a) => (
        <Attachment key={a.id} ticketId={ticketId} att={a} compact={compact} />
      ))}
    </div>
  );
}

function formatBytes(n) {
  if (!n) return "";
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)}KB`;
  return `${(n / 1024 / 1024).toFixed(1)}MB`;
}

function Attachment({ ticketId, att, compact }) {
  const url = `${API}/tickets/${ticketId}/attachments/${att.id}`;
  const dl = `${url}?download=1`;
  if (att.is_image) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        className="group relative block border border-slate-200 rounded overflow-hidden hover:border-[var(--ayci-accent)] transition-colors"
        title={`${att.filename} · ${formatBytes(att.size)}`}
        data-testid={`attachment-${att.id}`}
      >
        <img
          src={url}
          alt={att.filename}
          className={compact ? "h-16 w-16 object-cover" : "h-24 w-24 object-cover"}
          loading="lazy"
        />
        <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent text-white text-[10px] px-1 py-0.5 truncate opacity-0 group-hover:opacity-100 transition-opacity">
          {att.filename}
        </div>
      </a>
    );
  }
  return (
    <a
      href={dl}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1.5 px-2 py-1 bg-white border border-slate-200 hover:border-[var(--ayci-accent)] rounded text-xs transition-colors max-w-xs"
      title={`Download ${att.filename}`}
      data-testid={`attachment-${att.id}`}
    >
      <FileText className="w-3.5 h-3.5 text-[var(--ayci-ink-muted)] flex-shrink-0" />
      <span className="truncate text-[var(--ayci-ink)]">{att.filename}</span>
      <span className="text-[10px] text-[var(--ayci-ink-muted)] flex-shrink-0">
        {formatBytes(att.size)}
      </span>
      <Download className="w-3 h-3 text-[var(--ayci-ink-muted)] flex-shrink-0" />
    </a>
  );
}


function WhatsAppReplyPanel({ ticket, onSent }) {
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [templates, setTemplates] = useState([]);
  const [templatesLoaded, setTemplatesLoaded] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [showTemplates, setShowTemplates] = useState(false);

  // 24h session window — Wati requires templates after this
  const lastInbound = ticket.wati_last_inbound_at || ticket.created_at;
  const hoursSince = lastInbound ? (Date.now() - new Date(lastInbound).getTime()) / 3600000 : Infinity;
  const outOfWindow = hoursSince >= 24;
  // Live countdown — ticks every minute so the chip stays accurate without re-fetching.
  const [, _tickNow] = useState(0);
  useEffect(() => {
    if (outOfWindow || !lastInbound) return;
    const t = setInterval(() => _tickNow((n) => n + 1), 60_000);
    return () => clearInterval(t);
  }, [outOfWindow, lastInbound]);
  const hoursLeft = Math.max(0, 24 - hoursSince);
  const hh = Math.floor(hoursLeft);
  const mm = Math.floor((hoursLeft - hh) * 60);
  const closingSoon = !outOfWindow && hoursLeft < 2;
  const countdownLabel = `${hh}h ${mm.toString().padStart(2, "0")}m left`;

  const loadTemplates = async () => {
    if (templatesLoaded) return;
    try {
      const { data } = await apiClient.get("/wati/templates");
      setTemplates(data.templates || []);
      setTemplatesLoaded(true);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load templates");
    }
  };

  const handleSend = async () => {
    const text = body.trim();
    if (!text) return;
    setSending(true);
    try {
      await apiClient.post(`/wati/tickets/${ticket.id}/reply`, { body: text });
      setBody("");
      toast.success("WhatsApp reply sent");
      onSent && (await onSent());
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Send failed");
    } finally {
      setSending(false);
    }
  };

  const handleSendTemplate = async () => {
    if (!templateName) return;
    setSending(true);
    try {
      await apiClient.post(`/wati/tickets/${ticket.id}/template`, {
        template_name: templateName,
        broadcast_name: `ticket-${ticket.id}`,
        parameters: [],
      });
      setTemplateName("");
      toast.success("Template message sent");
      onSent && (await onSent());
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Template send failed");
    } finally {
      setSending(false);
    }
  };

  return (
    <div
      className="border border-emerald-200 bg-emerald-50/40 rounded-md p-3"
      data-testid="whatsapp-reply-panel"
    >
      <div className="flex items-center gap-2 mb-2">
        <MessageCircle className="w-4 h-4 text-emerald-700" />
        <span className="text-[11px] uppercase tracking-wider font-semibold text-emerald-800">
          WhatsApp reply · {ticket.wati_wa_id}
        </span>
        {outOfWindow ? (
          <span
            className="ml-auto text-[10px] font-bold bg-amber-100 text-amber-900 px-1.5 py-0.5 rounded border border-amber-200"
            data-testid="wa-window-expired-chip"
          >
            24H WINDOW EXPIRED
          </span>
        ) : lastInbound ? (
          <span
            className={`ml-auto text-[10px] font-semibold px-1.5 py-0.5 rounded border ${
              closingSoon
                ? "bg-amber-50 text-amber-800 border-amber-200"
                : "bg-emerald-50 text-emerald-800 border-emerald-200"
            }`}
            title={`Last inbound: ${new Date(lastInbound).toLocaleString("en-GB")}`}
            data-testid="wa-window-countdown-chip"
          >
            {countdownLabel}
          </span>
        ) : null}
      </div>

      {!outOfWindow ? (
        <div className="flex items-end gap-2">
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Type a WhatsApp reply…"
            rows={2}
            className={inputCls}
            data-testid="whatsapp-reply-input"
          />
          <Button
            onClick={handleSend}
            disabled={!body.trim() || sending}
            size="sm"
            data-testid="whatsapp-reply-send"
            className="bg-emerald-600 hover:bg-emerald-700"
          >
            {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </Button>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-amber-900">
            More than 24h since last student message — only pre-approved templates can be sent.
          </p>
          {!showTemplates ? (
            <Button
              variant="outline"
              size="sm"
              onClick={async () => {
                setShowTemplates(true);
                await loadTemplates();
              }}
              data-testid="whatsapp-load-templates"
            >
              Load templates
            </Button>
          ) : (
            <div className="flex items-end gap-2">
              <select
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
                className={inputCls}
                data-testid="whatsapp-template-select"
              >
                <option value="">Choose a template…</option>
                {templates.map((t) => {
                  const lang = typeof t.language === "object" ? (t.language?.text || t.language?.value) : t.language;
                  return (
                    <option key={t.name} value={t.name}>
                      {t.name}{lang ? ` (${lang})` : ""}
                    </option>
                  );
                })}
              </select>
              <Button
                onClick={handleSendTemplate}
                disabled={!templateName || sending}
                size="sm"
                data-testid="whatsapp-template-send"
                className="bg-emerald-600 hover:bg-emerald-700"
              >
                {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </Button>
            </div>
          )}
          {templateName && (
            <div className="text-xs text-[var(--ayci-ink-muted)] bg-white border border-slate-200 rounded p-2">
              {(templates.find((t) => t.name === templateName) || {}).body || "—"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


// -------------------- Generic UI helpers --------------------

const inputCls =
  "w-full text-sm border border-[var(--ayci-border)] rounded-md px-2.5 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-[var(--ayci-accent)]/40";

function Field({ label, required, children }) {
  return (
    <label className="block">
      <span className="text-[11px] uppercase tracking-wider font-semibold text-[var(--ayci-ink-muted)] block mb-1">
        {label} {required && <span className="text-rose-600">*</span>}
      </span>
      {children}
    </label>
  );
}

function Label({ children }) {
  return (
    <div className="text-[11px] uppercase tracking-wider font-semibold text-[var(--ayci-ink-muted)] mb-1">
      {children}
    </div>
  );
}

// ---------------------------------------------------------------- CircleReplyPanel
// For tickets created by the Circle DM bot. Reply posts back into the
// original Circle DM thread as the coach (Tessa) and disables the AI bot on
// that thread (state → human_takeover) so it doesn't speak over the team.
function CircleReplyPanel({ ticket, onSent }) {
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const coach = ticket?.circle_dm_meta?.coach_name || "the coach";

  const handleSend = async () => {
    const text = body.trim();
    if (!text) return;
    setSending(true);
    try {
      const { data } = await apiClient.post(`/circle/tickets/${ticket.id}/reply`, { body: text });
      setBody("");
      toast.success(`Reply posted in Circle as ${data.posted_as || coach}`);
      onSent && (await onSent());
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Send failed");
    } finally {
      setSending(false);
    }
  };

  return (
    <div
      className="border border-violet-200 bg-violet-50/40 rounded-md p-3"
      data-testid="circle-dm-reply-panel"
    >
      <div className="flex items-center gap-2 mb-2">
        <MessageCircle className="w-4 h-4 text-violet-700" />
        <span className="text-[11px] uppercase tracking-wider font-semibold text-violet-800">
          Circle DM reply · posts as {coach}
        </span>
      </div>
      <div className="text-[11px] text-violet-900/80 mb-2">
        Your message will appear in the student's Circle inbox as {coach}. The AI bot will stop auto-responding on this thread once you reply.
      </div>
      <div className="flex items-end gap-2">
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Type a reply to send in Circle…"
          rows={3}
          className={inputCls}
          data-testid="circle-dm-reply-input"
        />
        <Button
          onClick={handleSend}
          disabled={!body.trim() || sending}
          size="sm"
          data-testid="circle-dm-reply-send"
          className="bg-violet-600 hover:bg-violet-700"
        >
          {sending ? "Sending…" : "Send to Circle"}
        </Button>
      </div>
    </div>
  );
}


function Modal({ title, onClose, children, wide, testid }) {
  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
      onClick={onClose}
      data-testid={testid}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className={`bg-white rounded-lg shadow-xl w-full ${wide ? "max-w-3xl" : "max-w-lg"} max-h-[90vh] overflow-y-auto`}
      >
        <div className="px-5 py-3.5 border-b border-slate-100 flex items-center justify-between">
          <div className="font-display font-bold text-base text-[var(--ayci-ink)]">{title}</div>
          <button onClick={onClose} className="text-[var(--ayci-ink-muted)] hover:text-[var(--ayci-ink)]" data-testid="modal-close">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}
