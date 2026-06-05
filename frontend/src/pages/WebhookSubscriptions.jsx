/* Outbound webhook subscriptions — admin for the dispatcher that replaces
 * Monday "Specific Column Value Changed" triggers.
 *
 * Each subscription says: when COLUMN changes on a student (via a dashboard
 * edit or a migrated zap), POST a "column_changed" event to URL (a Zapier
 * "Webhooks by Zapier — Catch Hook"). The receiving zap then does its
 * Circle/Kit/Slack side-effects without triggering on Monday.
 *
 * Backend: /api/webhook-subscriptions (list/create/delete) +
 * /api/webhook-subscriptions/columns (allowed columns). See
 * backend/webhooks_outbound.py for the emit side.
 */
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Loader2, Plus, Trash2, RefreshCw, Webhook } from "lucide-react";
import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
  DialogFooter, DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from "@/components/ui/select";

function formatDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-GB", {
      day: "2-digit", month: "short", year: "numeric",
    });
  } catch {
    return iso;
  }
}

export default function WebhookSubscriptions() {
  const [subs, setSubs] = useState([]);
  const [columns, setColumns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState(null);

  // Create-form state
  const [name, setName] = useState("");
  const [column, setColumn] = useState("");
  const [url, setUrl] = useState("");

  const load = async () => {
    setRefreshing(true);
    try {
      const [subRes, colRes] = await Promise.all([
        apiClient.get("/webhook-subscriptions"),
        apiClient.get("/webhook-subscriptions/columns"),
      ]);
      setSubs(subRes.data.items || []);
      setColumns(colRes.data.columns || []);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to load subscriptions");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => { load(); }, []);

  const resetForm = () => {
    setName("");
    setColumn("");
    setUrl("");
  };

  const canSave = name.trim() && column && url.trim().startsWith("https://");

  const handleCreate = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      const { data } = await apiClient.post("/webhook-subscriptions", {
        name: name.trim(),
        column,
        url: url.trim(),
        active: true,
      });
      setSubs((prev) => [...prev, data].sort(
        (a, b) => (a.column || "").localeCompare(b.column || "") ||
                  (a.name || "").localeCompare(b.name || "")
      ));
      toast.success(`Subscription "${data.name}" created`);
      resetForm();
      setDialogOpen(false);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to create subscription");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (sub) => {
    if (!window.confirm(`Delete subscription "${sub.name}"? The zap listening on this URL will stop receiving events.`)) {
      return;
    }
    setDeletingId(sub.id);
    try {
      await apiClient.delete(`/webhook-subscriptions/${sub.id}`);
      setSubs((prev) => prev.filter((s) => s.id !== sub.id));
      toast.success("Subscription deleted");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Failed to delete subscription");
    } finally {
      setDeletingId(null);
    }
  };

  const grouped = useMemo(() => {
    const byCol = {};
    for (const s of subs) (byCol[s.column] ||= []).push(s);
    return byCol;
  }, [subs]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <Webhook className="h-6 w-6" /> Webhook Subscriptions
          </h1>
          <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
            When a column changes on a student — via a dashboard edit or a migrated
            zap — the dashboard POSTs a <code>column_changed</code> event to each
            URL subscribed to that column. Point a zap's "Webhooks by Zapier — Catch
            Hook" trigger here to replace its Monday "Specific Column Value Changed"
            trigger.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button variant="outline" size="icon" onClick={load} disabled={refreshing} title="Refresh">
            <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
          </Button>
          <Dialog open={dialogOpen} onOpenChange={(o) => { setDialogOpen(o); if (!o) resetForm(); }}>
            <DialogTrigger asChild>
              <Button><Plus className="h-4 w-4 mr-1" /> New subscription</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>New webhook subscription</DialogTitle>
                <DialogDescription>
                  Create a Zapier "Webhooks by Zapier → Catch Hook" trigger first, then
                  paste its URL here and pick the column to listen on.
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4 py-2">
                <div className="space-y-1.5">
                  <label className="text-sm font-medium">Name</label>
                  <Input
                    placeholder="e.g. 8b — Boss tagging on Circle"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-sm font-medium">Column</label>
                  <Select value={column} onValueChange={setColumn}>
                    <SelectTrigger><SelectValue placeholder="Pick a column…" /></SelectTrigger>
                    <SelectContent>
                      {columns.map((c) => (
                        <SelectItem key={c} value={c}>{c}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-sm font-medium">Catch-hook URL</label>
                  <Input
                    placeholder="https://hooks.zapier.com/hooks/catch/…"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                  />
                  {url && !url.trim().startsWith("https://") && (
                    <p className="text-xs text-destructive">URL must start with https://</p>
                  )}
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={saving}>
                  Cancel
                </Button>
                <Button onClick={handleCreate} disabled={!canSave || saving}>
                  {saving && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
                  Create
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {subs.length === 0 ? (
        <div className="border rounded-lg p-10 text-center text-muted-foreground">
          <Webhook className="h-8 w-8 mx-auto mb-3 opacity-40" />
          <p>No subscriptions yet.</p>
          <p className="text-sm mt-1">
            Create one to start replacing a Monday "Specific Column Value Changed" trigger.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(grouped).map(([col, list]) => (
            <div key={col}>
              <div className="flex items-center gap-2 mb-2">
                <Badge variant="secondary" className="font-mono">{col}</Badge>
                <span className="text-xs text-muted-foreground">
                  {list.length} subscriber{list.length === 1 ? "" : "s"}
                </span>
              </div>
              <div className="border rounded-lg divide-y">
                {list.map((s) => (
                  <div key={s.id} className="flex items-center justify-between gap-4 p-3">
                    <div className="min-w-0">
                      <div className="font-medium flex items-center gap-2">
                        {s.name}
                        {!s.active && <Badge variant="outline">inactive</Badge>}
                      </div>
                      <div className="text-xs text-muted-foreground truncate font-mono">{s.url}</div>
                      <div className="text-xs text-muted-foreground mt-0.5">
                        Added {formatDate(s.created_at)}{s.created_by ? ` by ${s.created_by}` : ""}
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="text-destructive shrink-0"
                      onClick={() => handleDelete(s)}
                      disabled={deletingId === s.id}
                      title="Delete subscription"
                    >
                      {deletingId === s.id
                        ? <Loader2 className="h-4 w-4 animate-spin" />
                        : <Trash2 className="h-4 w-4" />}
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
