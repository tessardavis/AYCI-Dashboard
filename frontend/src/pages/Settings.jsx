import { useCallback, useEffect, useState } from "react";
import { apiClient, formatApiErrorDetail } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogTrigger,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { Avatar, AvatarImage, AvatarFallback } from "@/components/ui/avatar";
import { Trash2, Plus, Link2, GripVertical } from "lucide-react";
import { DragDropContext, Droppable, Draggable } from "@hello-pangea/dnd";
import { formatValue } from "@/lib/format";
import MetricSourceDialog from "@/components/MetricSourceDialog";
import CohortMilestonesSection from "@/components/settings/CohortMilestonesSection";
import ConnectedInboxesSection from "@/components/settings/ConnectedInboxesSection";
import IntegrationsSection from "@/components/settings/IntegrationsSection";

const CATEGORIES = [
  "GROWTH + INTEREST",
  "CONVERSION + INTENT",
  "REVENUE",
  "SOCIAL PROOF",
  "DELIVERY + OPERATIONS",
];

export default function Settings() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  return (
    <div className="p-4 sm:p-6 lg:p-12 ayci-fade-up">
      <PageHeader
        eyebrow="Workspace"
        title="Settings"
        description={isAdmin ? "Manage team members, scorecard metrics, rocks and launches." : "View workspace configuration."}
      />

      {!isAdmin && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 text-sm rounded-md px-4 py-3 mb-6">
          Admin access is required to modify settings. Ask your admin for changes.
        </div>
      )}

      <Tabs defaultValue="team" className="w-full">
        <TabsList className="mb-6">
          <TabsTrigger value="team" data-testid="settings-tab-team">Team</TabsTrigger>
          <TabsTrigger value="users" data-testid="settings-tab-users">Users</TabsTrigger>
          <TabsTrigger value="metrics" data-testid="settings-tab-metrics">Metrics</TabsTrigger>
          <TabsTrigger value="rocks" data-testid="settings-tab-rocks">Rocks</TabsTrigger>
          <TabsTrigger value="launches" data-testid="settings-tab-launches">Launches</TabsTrigger>
          <TabsTrigger value="cohort" data-testid="settings-tab-cohort">Cohort</TabsTrigger>
          <TabsTrigger value="inboxes" data-testid="settings-tab-inboxes">Inboxes</TabsTrigger>
          <TabsTrigger value="integrations" data-testid="settings-tab-integrations">Integrations</TabsTrigger>
        </TabsList>
        <TabsContent value="team"><TeamSection isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="users"><UsersSection isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="metrics"><MetricsSection isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="rocks"><RocksSection isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="launches"><LaunchesSection isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="cohort"><CohortMilestonesSection isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="inboxes"><ConnectedInboxesSection isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="integrations"><IntegrationsSection isAdmin={isAdmin} /></TabsContent>
      </Tabs>
    </div>
  );
}

function Panel({ children, title, action, description }) {
  return (
    <div className="bg-white border border-[var(--ayci-border)] rounded-lg shadow-sm mb-4">
      <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--ayci-border)]">
        <div>
          <div className="font-display font-bold text-[var(--ayci-ink)]">{title}</div>
          {description && (
            <div className="text-xs text-[var(--ayci-ink-muted)] mt-0.5 max-w-2xl">{description}</div>
          )}
        </div>
        {action}
      </div>
      <div>{children}</div>
    </div>
  );
}

// -------- Team --------
function TeamSection({ isAdmin }) {
  const [team, setTeam] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", role_title: "", avatar_url: "" });

  const load = useCallback(async () => {
    const { data } = await apiClient.get("/team");
    setTeam(data);
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    try {
      await apiClient.post("/team", { ...form, avatar_url: form.avatar_url || null });
      toast.success("Member added");
      setOpen(false);
      setForm({ name: "", role_title: "", avatar_url: "" });
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  const remove = async (id) => {
    try {
      await apiClient.delete(`/team/${id}`);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  return (
    <>
    <Panel
      title="Team members"
      action={isAdmin && (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm" data-testid="team-add-btn" style={{ backgroundColor: "var(--ayci-accent)" }}>
              <Plus className="w-4 h-4 mr-1" /> Add member
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle>New team member</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div><Label>Name</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="team-form-name" /></div>
              <div><Label>Role</Label><Input value={form.role_title} onChange={(e) => setForm({ ...form, role_title: e.target.value })} data-testid="team-form-role" /></div>
              <div><Label>Avatar URL (optional)</Label><Input value={form.avatar_url} onChange={(e) => setForm({ ...form, avatar_url: e.target.value })} /></div>
            </div>
            <DialogFooter>
              <Button onClick={save} data-testid="team-form-save" style={{ backgroundColor: "var(--ayci-accent)" }}>Save</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    >
      <ul className="divide-y divide-[var(--ayci-border)]">
        {team.map((t) => (
          <li key={t.id} className="flex items-center gap-4 px-6 py-3" data-testid={`team-row-${t.id}`}>
            <Avatar className="w-9 h-9">
              {t.avatar_url && <AvatarImage src={t.avatar_url} alt={t.name} />}
              <AvatarFallback className="bg-slate-100 text-slate-700 text-xs">{t.name.split(" ").map(p => p[0]).slice(0, 2).join("")}</AvatarFallback>
            </Avatar>
            <div className="flex-1">
              <div className="font-medium text-[var(--ayci-ink)] text-sm">{t.name}</div>
              <div className="text-xs text-[var(--ayci-ink-muted)]">{t.role_title}</div>
            </div>
            {isAdmin && (
              <Button variant="ghost" size="icon" onClick={() => remove(t.id)} data-testid={`team-delete-${t.id}`}>
                <Trash2 className="w-4 h-4 text-slate-500" />
              </Button>
            )}
          </li>
        ))}
      </ul>
    </Panel>
    <InboxRoutingPanel isAdmin={isAdmin} team={team} />
    </>
  );
}

function InboxRoutingPanel({ isAdmin, team }) {
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/team/inbox-routing");
      setRules(
        (data.rules || []).map((r) => ({
          inbox_locals: (r.inbox_locals || []).join(", "),
          team_member_name: r.team_member_name || "",
        })),
      );
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to load");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const update = (i, field, value) => {
    setRules((prev) => prev.map((r, idx) => (idx === i ? { ...r, [field]: value } : r)));
  };
  const addRule = () => setRules((p) => [...p, { inbox_locals: "", team_member_name: "" }]);
  const removeRule = (i) => setRules((p) => p.filter((_, idx) => idx !== i));

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        rules: rules
          .map((r) => ({
            inbox_locals: r.inbox_locals
              .split(/[,\s]+/)
              .map((x) => x.trim().toLowerCase())
              .filter(Boolean),
            team_member_name: r.team_member_name.trim(),
          }))
          .filter((r) => r.inbox_locals.length > 0 && r.team_member_name),
      };
      const { data } = await apiClient.put("/team/inbox-routing", payload);
      setRules(
        (data.rules || []).map((r) => ({
          inbox_locals: (r.inbox_locals || []).join(", "),
          team_member_name: r.team_member_name || "",
        })),
      );
      toast.success("Inbox routing saved");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Panel
      title="Inbox auto-assignment"
      description="When an email lands in the listed inbox(es), the new ticket is auto-assigned to the chosen team member. Only the part before @ — comma-separated for multiple."
      action={isAdmin && (
        <Button size="sm" onClick={save} disabled={saving} data-testid="inbox-routing-save" style={{ backgroundColor: "var(--ayci-accent)" }}>
          {saving ? "Saving…" : "Save"}
        </Button>
      )}
    >
      {loading ? (
        <div className="px-6 py-4 text-sm text-[var(--ayci-ink-muted)]">Loading…</div>
      ) : (
        <div className="px-6 py-4 space-y-3">
          {rules.length === 0 && (
            <div className="text-xs text-[var(--ayci-ink-muted)] italic">No rules yet — add one below.</div>
          )}
          {rules.map((r, i) => (
            <div key={i} className="flex flex-wrap items-end gap-2" data-testid={`inbox-routing-row-${i}`}>
              <div className="flex-1 min-w-[220px]">
                <Label className="text-xs">Inbox local-parts</Label>
                <Input
                  value={r.inbox_locals}
                  onChange={(e) => update(i, "inbox_locals", e.target.value)}
                  placeholder="e.g. coralie, oksana"
                  disabled={!isAdmin}
                  data-testid={`inbox-routing-locals-${i}`}
                />
              </div>
              <div className="flex-1 min-w-[200px]">
                <Label className="text-xs">Assign to</Label>
                <select
                  value={r.team_member_name}
                  onChange={(e) => update(i, "team_member_name", e.target.value)}
                  disabled={!isAdmin}
                  className="w-full h-9 px-3 text-sm border border-[var(--ayci-border)] rounded-md bg-white"
                  data-testid={`inbox-routing-assignee-${i}`}
                >
                  <option value="">— pick a team member —</option>
                  {team.map((t) => (
                    <option key={t.id} value={t.name}>{t.name}</option>
                  ))}
                </select>
              </div>
              {isAdmin && (
                <Button variant="ghost" size="icon" onClick={() => removeRule(i)} data-testid={`inbox-routing-remove-${i}`}>
                  <Trash2 className="w-4 h-4 text-slate-500" />
                </Button>
              )}
            </div>
          ))}
          {isAdmin && (
            <Button variant="outline" size="sm" onClick={addRule} data-testid="inbox-routing-add">
              <Plus className="w-4 h-4 mr-1" /> Add rule
            </Button>
          )}
        </div>
      )}
    </Panel>
  );
}

// -------- Users (login accounts) --------
const BOARD_LABELS = {
  weekly_scorecard: "Weekly Scorecard",
  quarterly_rocks: "Quarterly Rocks",
  launches: "Launch Dashboard",
  cohort: "Cohort Dashboard",
  interviews: "Upcoming Interviews",
  students: "Student Lookup",
  at_risk: "Students at Risk",
};

function UsersSection({ isAdmin }) {
  const [users, setUsers] = useState([]);
  const [allBoards, setAllBoards] = useState([]);
  const [teamMembers, setTeamMembers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    name: "",
    email: "",
    password: "",
    role: "user",
    board_access: [],
  });

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/admin/users");
      setUsers(data.users || []);
      setAllBoards(data.all_boards || []);
      setTeamMembers(data.team_members || []);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to load users");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isAdmin) load();
  }, [isAdmin]);

  const create = async () => {
    setBusy(true);
    try {
      await apiClient.post("/auth/register", form);
      toast.success(`Invited ${form.email}`);
      setForm({ name: "", email: "", password: "", role: "user", board_access: [] });
      await load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    } finally {
      setBusy(false);
    }
  };

  const updateUser = async (userId, patch) => {
    try {
      await apiClient.patch(`/admin/users/${userId}`, patch);
      toast.success("Saved");
      await load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  const deleteUser = async (userId, email) => {
    if (!window.confirm(`Delete user ${email}? This cannot be undone.`)) return;
    try {
      await apiClient.delete(`/admin/users/${userId}`);
      toast.success("User deleted");
      await load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  const toggleBoard = (user, board) => {
    if (user.role === "admin") return; // admins always have everything
    const has = (user.board_access || []).includes(board);
    const next = has
      ? (user.board_access || []).filter((b) => b !== board)
      : [...(user.board_access || []), board];
    updateUser(user.id, { board_access: next });
  };

  if (!isAdmin) {
    return <div className="text-sm text-[var(--ayci-ink-muted)]">Admin only.</div>;
  }

  return (
    <div className="space-y-6">
      <Panel title="Invite a new user">
        <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-4 max-w-2xl">
          <div>
            <Label>Name</Label>
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              data-testid="user-form-name"
            />
          </div>
          <div>
            <Label>Email</Label>
            <Input
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              data-testid="user-form-email"
            />
          </div>
          <div>
            <Label>Temporary password</Label>
            <Input
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              data-testid="user-form-password"
            />
          </div>
          <div>
            <Label>Role</Label>
            <Select
              value={form.role}
              onValueChange={(v) => setForm({ ...form, role: v })}
            >
              <SelectTrigger data-testid="user-form-role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="user">User</SelectItem>
                <SelectItem value="admin">Admin (full access)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {form.role === "user" && (
            <div className="md:col-span-2">
              <Label>Board access</Label>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mt-1">
                {allBoards.map((b) => (
                  <label
                    key={b}
                    className="flex items-center gap-2 text-xs bg-slate-50 border border-[var(--ayci-border)] rounded px-3 py-2 cursor-pointer hover:border-[var(--ayci-accent)]"
                  >
                    <input
                      type="checkbox"
                      checked={form.board_access.includes(b)}
                      onChange={(e) => {
                        const next = e.target.checked
                          ? [...form.board_access, b]
                          : form.board_access.filter((x) => x !== b);
                        setForm({ ...form, board_access: next });
                      }}
                      data-testid={`user-form-board-${b}`}
                    />
                    {BOARD_LABELS[b] || b}
                  </label>
                ))}
              </div>
            </div>
          )}
          <div className="md:col-span-2">
            <Button
              onClick={create}
              disabled={busy || !form.email || !form.password || !form.name}
              data-testid="user-form-save"
              style={{ backgroundColor: "var(--ayci-accent)" }}
            >
              {busy ? "Inviting…" : "Invite user"}
            </Button>
          </div>
        </div>
      </Panel>

      <Panel
        title={`Existing users (${users.length})`}
        action={
          users.filter((u) => u.role !== "admin" && !u.team_member_id).length > 0 ? (
            <span
              className="text-[10px] uppercase tracking-wider font-semibold px-2 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-800"
              data-testid="users-unlinked-badge"
            >
              ⚠ {users.filter((u) => u.role !== "admin" && !u.team_member_id).length} not linked
            </span>
          ) : null
        }
      >
        {loading ? (
          <div className="p-6 text-sm text-[var(--ayci-ink-muted)]">Loading…</div>
        ) : (
          <div className="divide-y divide-[var(--ayci-border)]">
            {users.map((u) => (
              <div key={u.id} className="p-4" data-testid={`user-row-${u.id}`}>
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <div className="font-semibold text-[var(--ayci-ink)]">
                      {u.name}{" "}
                      <span className="text-xs font-normal text-[var(--ayci-ink-muted)]">
                        ({u.email})
                      </span>
                    </div>
                    <div className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] mt-0.5">
                      {u.role === "admin" ? "Admin · full access" : "User"}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Select
                      value={u.role}
                      onValueChange={(v) => updateUser(u.id, { role: v })}
                    >
                      <SelectTrigger
                        className="h-8 text-xs"
                        data-testid={`user-row-role-${u.id}`}
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="user">User</SelectItem>
                        <SelectItem value="admin">Admin</SelectItem>
                      </SelectContent>
                    </Select>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => deleteUser(u.id, u.email)}
                      data-testid={`user-row-delete-${u.id}`}
                      className="text-rose-600 hover:bg-rose-50"
                    >
                      Delete
                    </Button>
                  </div>
                </div>
                {u.role === "user" && (
                  <>
                    <div className="mt-3 flex items-center gap-2 flex-wrap" data-testid={`user-tm-row-${u.id}`}>
                      <span className="text-[10px] uppercase tracking-wider text-[var(--ayci-ink-muted)] font-semibold">
                        Team member:
                      </span>
                      <Select
                        value={u.team_member_id || "__none__"}
                        onValueChange={(v) =>
                          updateUser(u.id, { team_member_id: v === "__none__" ? "" : v })
                        }
                      >
                        <SelectTrigger
                          className="h-7 w-[200px] text-xs"
                          data-testid={`user-tm-select-${u.id}`}
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__none__">— Not linked —</SelectItem>
                          {teamMembers.map((tm) => (
                            <SelectItem
                              key={tm.id}
                              value={tm.id}
                              data-testid={`user-tm-option-${u.id}-${tm.id}`}
                            >
                              {tm.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {!u.team_member_id && (
                        <span className="text-[10px] text-amber-700">
                          Can't edit any rocks until linked
                        </span>
                      )}
                    </div>
                    <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-1.5">
                    {allBoards.map((b) => {
                      const has = (u.board_access || []).includes(b);
                      return (
                        <button
                          key={b}
                          onClick={() => toggleBoard(u, b)}
                          data-testid={`user-row-board-${u.id}-${b}`}
                          className={
                            "text-[11px] px-2 py-1 rounded border transition-colors " +
                            (has
                              ? "bg-[var(--ayci-accent)]/10 border-[var(--ayci-accent)] text-[var(--ayci-accent)] font-semibold"
                              : "bg-white border-[var(--ayci-border)] text-[var(--ayci-ink-muted)] hover:border-[var(--ayci-accent)]")
                          }
                        >
                          {has ? "✓" : "+"} {BOARD_LABELS[b] || b}
                        </button>
                      );
                    })}
                  </div>
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

// -------- Metrics --------
function MetricsSection({ isAdmin }) {
  const [metrics, setMetrics] = useState([]);
  const [team, setTeam] = useState([]);
  const [open, setOpen] = useState(false);
  const [sourceMetric, setSourceMetric] = useState(null);
  const [form, setForm] = useState({ name: "", category: "GROWTH + INTEREST", owner_ids: [], goal: 0, format: "number", goal_direction: "above" });

  const load = useCallback(async () => {
    const [m, t] = await Promise.all([apiClient.get("/metrics"), apiClient.get("/team")]);
    setMetrics(m.data); setTeam(t.data);
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    try {
      await apiClient.post("/metrics", { ...form, goal: Number(form.goal) });
      toast.success("Metric added");
      setOpen(false);
      setForm({ name: "", category: "GROWTH + INTEREST", owner_ids: [], goal: 0, format: "number", goal_direction: "above" });
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  const remove = async (id) => {
    await apiClient.delete(`/metrics/${id}`);
    load();
  };

  const toggleOwner = (id) => {
    setForm((f) => ({
      ...f,
      owner_ids: f.owner_ids.includes(id) ? f.owner_ids.filter((x) => x !== id) : [...f.owner_ids, id],
    }));
  };

  return (
    <Panel
      title="Scorecard metrics"
      action={isAdmin && (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm" data-testid="metric-add-btn" style={{ backgroundColor: "var(--ayci-accent)" }}>
              <Plus className="w-4 h-4 mr-1" /> Add metric
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-lg">
            <DialogHeader><DialogTitle>New metric</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div><Label>Name</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="metric-form-name" /></div>
              <div>
                <Label>Category</Label>
                <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <Label>Goal</Label>
                  <Input type="number" value={form.goal} onChange={(e) => setForm({ ...form, goal: e.target.value })} data-testid="metric-form-goal" />
                </div>
                <div>
                  <Label>Format</Label>
                  <Select value={form.format} onValueChange={(v) => setForm({ ...form, format: v })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="number">Number</SelectItem>
                      <SelectItem value="currency">Currency (£)</SelectItem>
                      <SelectItem value="percentage">Percentage (%)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Direction</Label>
                  <Select value={form.goal_direction} onValueChange={(v) => setForm({ ...form, goal_direction: v })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="above">Higher is better</SelectItem>
                      <SelectItem value="below">Lower is better</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div>
                <Label>Owners</Label>
                <div className="flex flex-wrap gap-2 mt-2">
                  {team.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => toggleOwner(t.id)}
                      className={
                        "text-xs px-2.5 py-1 rounded-full border transition-colors " +
                        (form.owner_ids.includes(t.id)
                          ? "bg-[var(--ayci-accent)] text-white border-[var(--ayci-accent)]"
                          : "bg-white border-[var(--ayci-border)] text-[var(--ayci-ink-muted)]")
                      }
                    >
                      {t.name}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button onClick={save} data-testid="metric-form-save" style={{ backgroundColor: "var(--ayci-accent)" }}>Save</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    >
      <table className="w-full text-sm">
        <thead className="bg-slate-50 border-b border-[var(--ayci-border)]">
          <tr>
            {isAdmin && <th className="w-8" />}
            <th className="text-left px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Name</th>
            <th className="text-right px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Goal</th>
            <th className="text-left px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Format</th>
            <th className="text-left px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Source</th>
            {isAdmin && <th />}
          </tr>
        </thead>
        <DragDropContext
          onDragEnd={async (result) => {
            if (!isAdmin) return;
            if (!result.destination) return;
            const category = result.source.droppableId;
            if (result.destination.droppableId !== category) return;

            const groupMetrics = metrics
              .filter((m) => m.category === category)
              .sort((a, b) => a.order - b.order);
            const [moved] = groupMetrics.splice(result.source.index, 1);
            groupMetrics.splice(result.destination.index, 0, moved);

            // Re-assign orders in this category starting from the min order
            const minOrder = Math.min(...groupMetrics.map((m) => m.order));
            const updates = groupMetrics.map((m, i) => ({ id: m.id, order: minOrder + i }));

            // Optimistic UI
            setMetrics((prev) =>
              prev.map((m) => {
                const u = updates.find((x) => x.id === m.id);
                return u ? { ...m, order: u.order } : m;
              }),
            );

            try {
              await apiClient.patch("/metrics/reorder", { order: updates });
              toast.success("Reordered");
            } catch (err) {
              toast.error(
                formatApiErrorDetail(err.response?.data?.detail) || "Reorder failed",
              );
              load(); // rollback
            }
          }}
        >
          {CATEGORIES.map((cat) => {
            const rows = metrics
              .filter((m) => m.category === cat)
              .sort((a, b) => a.order - b.order);
            if (rows.length === 0) return null;
            return (
              <tbody key={cat}>
                <tr className="bg-slate-50/50">
                  <td
                    colSpan={isAdmin ? 6 : 5}
                    className="px-6 py-1.5 text-[10px] font-display font-semibold uppercase tracking-[0.2em] text-[var(--ayci-teal)] border-t border-b border-[var(--ayci-border)]"
                  >
                    {cat}
                  </td>
                </tr>
                <Droppable droppableId={cat} isDropDisabled={!isAdmin}>
                  {(dropProv) => (
                    <>
                      {rows.map((m, idx) => (
                        <Draggable key={m.id} draggableId={m.id} index={idx} isDragDisabled={!isAdmin}>
                          {(dragProv, snap) => (
                            <tr
                              ref={dragProv.innerRef}
                              {...dragProv.draggableProps}
                              className={
                                "border-b border-[var(--ayci-border)] last:border-0 " +
                                (snap.isDragging ? "bg-amber-50 shadow-md" : "")
                              }
                              style={dragProv.draggableProps.style}
                              data-testid={`metric-row-${m.id}`}
                            >
                              {isAdmin && (
                                <td
                                  className="px-2 text-slate-300 cursor-grab active:cursor-grabbing hover:text-slate-600"
                                  {...dragProv.dragHandleProps}
                                  data-testid={`metric-drag-${m.id}`}
                                >
                                  <GripVertical className="w-4 h-4" />
                                </td>
                              )}
                              <td className="px-6 py-2.5 font-medium text-[var(--ayci-ink)]">
                                {m.name}
                              </td>
                              <td className="px-6 py-2.5 text-right metric-number">
                                {formatValue(m.goal, m.format)}
                              </td>
                              <td className="px-6 py-2.5 capitalize text-[var(--ayci-ink-muted)]">
                                {m.format}
                              </td>
                              <td className="px-6 py-2.5">
                                {m.source_type ? (
                                  <button
                                    onClick={() => isAdmin && setSourceMetric(m)}
                                    className="inline-flex items-center gap-1.5 text-[11px] px-2 py-0.5 rounded-full bg-sky-50 text-sky-700 ring-1 ring-sky-200 hover:bg-sky-100"
                                    data-testid={`metric-source-${m.id}`}
                                  >
                                    <Link2 className="w-3 h-3" />
                                    {m.source_type.replace(/_/g, " ")}
                                  </button>
                                ) : isAdmin ? (
                                  <button
                                    onClick={() => setSourceMetric(m)}
                                    className="text-[11px] text-[var(--ayci-accent)] hover:underline"
                                    data-testid={`metric-source-${m.id}`}
                                  >
                                    + Connect source
                                  </button>
                                ) : (
                                  <span className="text-xs text-[var(--ayci-ink-muted)]">manual</span>
                                )}
                              </td>
                              {isAdmin && (
                                <td className="px-6 py-2.5 text-right">
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    onClick={() => remove(m.id)}
                                    data-testid={`metric-delete-${m.id}`}
                                  >
                                    <Trash2 className="w-4 h-4 text-slate-500" />
                                  </Button>
                                </td>
                              )}
                            </tr>
                          )}
                        </Draggable>
                      ))}
                      <tr ref={dropProv.innerRef} {...dropProv.droppableProps} className="h-0">
                        <td colSpan={isAdmin ? 6 : 5}>{dropProv.placeholder}</td>
                      </tr>
                    </>
                  )}
                </Droppable>
              </tbody>
            );
          })}
        </DragDropContext>
      </table>
      <MetricSourceDialog
        open={!!sourceMetric}
        onOpenChange={(o) => !o && setSourceMetric(null)}
        metric={sourceMetric}
        onSaved={load}
      />
    </Panel>
  );
}

// -------- Rocks --------
function RocksSection({ isAdmin }) {
  const [rocks, setRocks] = useState([]);
  const [team, setTeam] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ owner_id: "", title: "", status: "on_track", due_date: "2026-06-30", notes: "", quarter: "Q2 2026" });
  const [quarters, setQuarters] = useState([]);
  const [activeQuarter, setActiveQuarter] = useState(null);
  const [savingActive, setSavingActive] = useState(false);

  const load = useCallback(async () => {
    const [r, t, q] = await Promise.all([
      apiClient.get("/rocks"),
      apiClient.get("/team"),
      apiClient.get("/rocks/quarters"),
    ]);
    setRocks(r.data); setTeam(t.data);
    const qd = q.data;
    setQuarters(Array.isArray(qd) ? qd : qd.quarters || []);
    setActiveQuarter(Array.isArray(qd) ? null : qd.active);
  }, []);
  useEffect(() => { load(); }, [load]);

  const setActive = async (q) => {
    if (!isAdmin || !q) return;
    setSavingActive(true);
    try {
      const { data } = await apiClient.put("/rocks/active-quarter", { quarter: q });
      setActiveQuarter(data.active);
      toast.success(`Active quarter set to ${data.active}`);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to set active quarter");
    } finally {
      setSavingActive(false);
    }
  };

  const save = async () => {
    try {
      await apiClient.post("/rocks", form);
      toast.success("Rock added");
      setOpen(false);
      setForm({ owner_id: "", title: "", status: "on_track", due_date: "2026-06-30", notes: "", quarter: "Q2 2026" });
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  const remove = async (id) => {
    await apiClient.delete(`/rocks/${id}`);
    load();
  };

  const teamById = Object.fromEntries(team.map((t) => [t.id, t]));

  return (
    <Panel
      title="Quarterly rocks"
      action={isAdmin && (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm" data-testid="rock-add-btn" style={{ backgroundColor: "var(--ayci-accent)" }}>
              <Plus className="w-4 h-4 mr-1" /> Add rock
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle>New rock</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div><Label>Title</Label><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} data-testid="rock-form-title" /></div>
              <div>
                <Label>Owner</Label>
                <Select value={form.owner_id} onValueChange={(v) => setForm({ ...form, owner_id: v })}>
                  <SelectTrigger data-testid="rock-form-owner"><SelectValue placeholder="Choose owner" /></SelectTrigger>
                  <SelectContent>
                    {team.map((t) => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label>Quarter</Label>
                  <Input value={form.quarter} onChange={(e) => setForm({ ...form, quarter: e.target.value })} data-testid="rock-form-quarter" />
                </div>
                <div>
                  <Label>Due date</Label>
                  <Input type="date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button onClick={save} data-testid="rock-form-save" style={{ backgroundColor: "var(--ayci-accent)" }}>Save</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    >
      {quarters.length > 0 && (
        <div
          className="px-5 py-4 border-b border-[var(--ayci-border)] bg-slate-50/50 flex items-center gap-3 flex-wrap"
          data-testid="active-quarter-panel"
        >
          <div className="flex-1 min-w-[200px]">
            <div className="text-[10px] uppercase tracking-wider font-semibold text-[var(--ayci-ink-muted)]">
              Active quarter
            </div>
            <div className="text-sm text-[var(--ayci-ink)] mt-0.5">
              Rocks in other quarters become read-only for non-admin users.
            </div>
          </div>
          <Select
            value={activeQuarter || ""}
            onValueChange={setActive}
            disabled={!isAdmin || savingActive}
          >
            <SelectTrigger className="w-[200px] bg-white" data-testid="active-quarter-select">
              <SelectValue placeholder="Pick active quarter" />
            </SelectTrigger>
            <SelectContent>
              {quarters.map((q) => (
                <SelectItem key={q} value={q} data-testid={`active-quarter-option-${q}`}>
                  {q}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      <ul className="divide-y divide-[var(--ayci-border)]">
        {rocks.map((r) => (
          <li key={r.id} className="px-6 py-3 flex items-center gap-4">
            <div className="w-32 text-xs text-[var(--ayci-ink-muted)]">{teamById[r.owner_id]?.name || "—"}</div>
            <div className="flex-1 text-sm">{r.title}</div>
            <div className="text-xs text-[var(--ayci-ink-muted)] flex items-center gap-1">
              {r.quarter}
              {r.quarter === activeQuarter && (
                <span className="text-[9px] px-1 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 uppercase tracking-wider font-semibold">
                  Active
                </span>
              )}
            </div>
            <div className="text-xs text-[var(--ayci-ink-muted)] capitalize">{r.status.replace("_", " ")}</div>
            {isAdmin && (
              <Button variant="ghost" size="icon" onClick={() => remove(r.id)} data-testid={`rock-delete-${r.id}`}>
                <Trash2 className="w-4 h-4 text-slate-500" />
              </Button>
            )}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

// -------- Launches --------
const PHASE_KEYS = [
  ["in_between_start", "In-between (start)"],
  ["early_access", "Early access"],
  ["flash_sale", "Flash sale"],
  ["webinar", "Webinar"],
  ["open_cart", "Open cart"],
  ["close_cart", "Close cart"],
  ["in_between_end", "In-between (end)"],
];

function LaunchesSection({ isAdmin }) {
  const [launches, setLaunches] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", code: "", start_date: "", end_date: "", webinar_date: "", target_good: 140000, target_better: 160000, target_best: 200000 });
  const [editing, setEditing] = useState(null); // launch object being edited

  const load = useCallback(async () => {
    const { data } = await apiClient.get("/launches");
    setLaunches(data);
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    try {
      await apiClient.post("/launches", {
        ...form,
        target_good: Number(form.target_good),
        target_better: Number(form.target_better),
        target_best: Number(form.target_best),
      });
      toast.success("Launch created");
      setOpen(false);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  const remove = async (id) => {
    await apiClient.delete(`/launches/${id}`);
    load();
  };

  const saveEdit = async () => {
    try {
      await apiClient.patch(`/launches/${editing.id}`, {
        name: editing.name,
        code: editing.code,
        start_date: editing.start_date,
        end_date: editing.end_date,
        webinar_date: editing.webinar_date,
        target_good: Number(editing.target_good),
        target_better: Number(editing.target_better),
        target_best: Number(editing.target_best),
        phases: editing.phases,
      });
      toast.success("Launch updated");
      setEditing(null);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    }
  };

  const setEditingPhase = (key, field, value) => {
    setEditing((cur) => ({
      ...cur,
      phases: {
        ...(cur.phases || {}),
        [key]: { ...((cur.phases || {})[key] || {}), [field]: value },
      },
    }));
  };

  return (
    <Panel
      title="Launches"
      action={isAdmin && (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm" data-testid="launch-add-btn" style={{ backgroundColor: "var(--ayci-accent)" }}>
              <Plus className="w-4 h-4 mr-1" /> Add launch
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle>New launch</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div><Label>Name</Label><Input placeholder="e.g. September 2026" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="launch-form-name" /></div>
              <div><Label>Kit tag code</Label><Input placeholder="e.g. SEP-26 (matches '[AYCI SEP-26] Webinar - Registered - X' tags)" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} data-testid="launch-form-code" /></div>
              <div className="grid grid-cols-3 gap-3">
                <div><Label>Start date</Label><Input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} /></div>
                <div><Label>End date</Label><Input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} /></div>
                <div><Label>Webinar date</Label><Input type="date" value={form.webinar_date} onChange={(e) => setForm({ ...form, webinar_date: e.target.value })} /></div>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div><Label>Good (£)</Label><Input type="number" value={form.target_good} onChange={(e) => setForm({ ...form, target_good: e.target.value })} /></div>
                <div><Label>Better (£)</Label><Input type="number" value={form.target_better} onChange={(e) => setForm({ ...form, target_better: e.target.value })} /></div>
                <div><Label>Best (£)</Label><Input type="number" value={form.target_best} onChange={(e) => setForm({ ...form, target_best: e.target.value })} /></div>
              </div>
              <p className="text-xs text-[var(--ayci-ink-muted)]">Phase dates can be set after creating — click "Edit phases" on the launch row.</p>
            </div>
            <DialogFooter>
              <Button onClick={save} data-testid="launch-form-save" style={{ backgroundColor: "var(--ayci-accent)" }}>Save</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    >
      <ul className="divide-y divide-[var(--ayci-border)]">
        {launches.map((l) => (
          <li key={l.id} className="px-6 py-3 flex items-center gap-4">
            <div className="font-display font-bold text-[var(--ayci-ink)] w-40">{l.name}</div>
            <div className="text-xs text-[var(--ayci-ink-muted)] w-24">{l.code || "—"}</div>
            <div className="text-xs text-[var(--ayci-ink-muted)] w-44">Webinar: {l.webinar_date}</div>
            <div className="flex-1 text-xs text-[var(--ayci-ink-muted)]">
              £{Number(l.target_good / 1000).toFixed(0)}k / £{Number(l.target_better / 1000).toFixed(0)}k / £{Number(l.target_best / 1000).toFixed(0)}k
            </div>
            {isAdmin && (
              <>
                <Button variant="outline" size="sm" onClick={() => setEditing({ ...l, phases: l.phases || {} })} data-testid={`launch-edit-${l.id}`}>
                  Edit
                </Button>
                <Button variant="ghost" size="icon" onClick={() => remove(l.id)} data-testid={`launch-delete-${l.id}`}>
                  <Trash2 className="w-4 h-4 text-slate-500" />
                </Button>
              </>
            )}
          </li>
        ))}
      </ul>

      {/* Edit dialog */}
      <Dialog open={!!editing} onOpenChange={(v) => !v && setEditing(null)}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Edit launch — {editing?.name}</DialogTitle>
          </DialogHeader>
          {editing && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Name</Label><Input value={editing.name || ""} onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></div>
                <div><Label>Kit tag code</Label><Input value={editing.code || ""} onChange={(e) => setEditing({ ...editing, code: e.target.value.toUpperCase() })} placeholder="e.g. APR-26" data-testid="launch-edit-code" /></div>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div><Label>Start date</Label><Input type="date" value={editing.start_date || ""} onChange={(e) => setEditing({ ...editing, start_date: e.target.value })} /></div>
                <div><Label>End date</Label><Input type="date" value={editing.end_date || ""} onChange={(e) => setEditing({ ...editing, end_date: e.target.value })} /></div>
                <div><Label>Webinar date</Label><Input type="date" value={editing.webinar_date || ""} onChange={(e) => setEditing({ ...editing, webinar_date: e.target.value })} /></div>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div><Label>Good (£)</Label><Input type="number" value={editing.target_good || 0} onChange={(e) => setEditing({ ...editing, target_good: e.target.value })} /></div>
                <div><Label>Better (£)</Label><Input type="number" value={editing.target_better || 0} onChange={(e) => setEditing({ ...editing, target_better: e.target.value })} /></div>
                <div><Label>Best (£)</Label><Input type="number" value={editing.target_best || 0} onChange={(e) => setEditing({ ...editing, target_best: e.target.value })} /></div>
              </div>

              <div className="border-t border-[var(--ayci-border)] pt-4">
                <h3 className="font-display font-bold text-sm text-[var(--ayci-ink)] mb-2">Launch phases</h3>
                <p className="text-xs text-[var(--ayci-ink-muted)] mb-3">
                  Use date+time format (datetime-local). The phase timeline on the Launch Dashboard reads these.
                </p>
                <div className="space-y-2">
                  {PHASE_KEYS.map(([key, label]) => {
                    const ph = (editing.phases || {})[key] || {};
                    const trim = (s) => (s ? s.replace("Z", "").slice(0, 16) : "");
                    return (
                      <div key={key} className="grid grid-cols-[140px_1fr_1fr] gap-2 items-center">
                        <span className="text-sm font-medium">{label}</span>
                        <Input
                          type="datetime-local"
                          value={trim(ph.start)}
                          onChange={(e) => setEditingPhase(key, "start", e.target.value ? `${e.target.value}:00Z` : null)}
                          data-testid={`phase-${key}-start`}
                        />
                        <Input
                          type="datetime-local"
                          value={trim(ph.end)}
                          onChange={(e) => setEditingPhase(key, "end", e.target.value ? `${e.target.value}:00Z` : null)}
                          data-testid={`phase-${key}-end`}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button onClick={saveEdit} data-testid="launch-edit-save" style={{ backgroundColor: "var(--ayci-accent)" }}>
              Save changes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Panel>
  );
}
