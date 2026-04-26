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
import { Trash2, Plus, Link2 } from "lucide-react";
import { formatValue } from "@/lib/format";
import MetricSourceDialog from "@/components/MetricSourceDialog";

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
    <div className="p-8 lg:p-12 ayci-fade-up">
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
        </TabsList>
        <TabsContent value="team"><TeamSection isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="users"><UsersSection isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="metrics"><MetricsSection isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="rocks"><RocksSection isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="launches"><LaunchesSection isAdmin={isAdmin} /></TabsContent>
      </Tabs>
    </div>
  );
}

function Panel({ children, title, action }) {
  return (
    <div className="bg-white border border-[var(--ayci-border)] rounded-lg shadow-sm">
      <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--ayci-border)]">
        <div className="font-display font-bold text-[var(--ayci-ink)]">{title}</div>
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
  );
}

// -------- Users (login accounts) --------
function UsersSection({ isAdmin }) {
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "user" });
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      await apiClient.post("/auth/register", form);
      toast.success("User created");
      setForm({ name: "", email: "", password: "", role: "user" });
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!isAdmin) return <div className="text-sm text-[var(--ayci-ink-muted)]">Admin only.</div>;

  return (
    <Panel title="Create login account">
      <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-4 max-w-2xl">
        <div><Label>Name</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="user-form-name" /></div>
        <div><Label>Email</Label><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} data-testid="user-form-email" /></div>
        <div><Label>Password</Label><Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} data-testid="user-form-password" /></div>
        <div>
          <Label>Role</Label>
          <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
            <SelectTrigger data-testid="user-form-role"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="user">User</SelectItem>
              <SelectItem value="admin">Admin</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="md:col-span-2">
          <Button onClick={save} disabled={busy} data-testid="user-form-save" style={{ backgroundColor: "var(--ayci-accent)" }}>
            {busy ? "Creating…" : "Create user"}
          </Button>
        </div>
      </div>
    </Panel>
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
            <th className="text-left px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Name</th>
            <th className="text-left px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Category</th>
            <th className="text-right px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Goal</th>
            <th className="text-left px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Format</th>
            <th className="text-left px-6 py-3 font-medium text-[var(--ayci-ink-muted)]">Source</th>
            {isAdmin && <th />}
          </tr>
        </thead>
        <tbody>
          {metrics.map((m) => (
            <tr key={m.id} className="border-b border-[var(--ayci-border)] last:border-0">
              <td className="px-6 py-2.5 font-medium text-[var(--ayci-ink)]">{m.name}</td>
              <td className="px-6 py-2.5 text-xs text-[var(--ayci-ink-muted)]">{m.category}</td>
              <td className="px-6 py-2.5 text-right metric-number">{formatValue(m.goal, m.format)}</td>
              <td className="px-6 py-2.5 capitalize text-[var(--ayci-ink-muted)]">{m.format}</td>
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
                  <Button variant="ghost" size="icon" onClick={() => remove(m.id)} data-testid={`metric-delete-${m.id}`}>
                    <Trash2 className="w-4 h-4 text-slate-500" />
                  </Button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
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

  const load = useCallback(async () => {
    const [r, t] = await Promise.all([apiClient.get("/rocks"), apiClient.get("/team")]);
    setRocks(r.data); setTeam(t.data);
  }, []);
  useEffect(() => { load(); }, [load]);

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
      <ul className="divide-y divide-[var(--ayci-border)]">
        {rocks.map((r) => (
          <li key={r.id} className="px-6 py-3 flex items-center gap-4">
            <div className="w-32 text-xs text-[var(--ayci-ink-muted)]">{teamById[r.owner_id]?.name || "—"}</div>
            <div className="flex-1 text-sm">{r.title}</div>
            <div className="text-xs text-[var(--ayci-ink-muted)]">{r.quarter}</div>
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
  ["early_signups", "Early signups"],
  ["flash_sale", "Flash sale"],
  ["webinar", "Webinar"],
  ["open_cart", "Open cart"],
  ["legacy_upgrades", "Legacy upgrades"],
  ["close_cart", "Close cart"],
  ["in_between", "In-between"],
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
