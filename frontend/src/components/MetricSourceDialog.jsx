import { useEffect, useMemo, useState } from "react";
import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { Zap, Unplug, RefreshCw } from "lucide-react";

const CONNECTORS = [
  { key: "", label: "— No source (manual only) —" },
  { key: "transistor_weekly_downloads", label: "Transistor — weekly downloads for a show", fields: ["show_id"] },
  { key: "convertkit_new_subscribers", label: "ConvertKit — total new subscribers", fields: [] },
  { key: "convertkit_tag_new_subscribers", label: "ConvertKit — new subscribers added to a tag", fields: ["tag_id"] },
  { key: "convertkit_broadcast_ctr", label: "ConvertKit — avg broadcast click-through rate", fields: [] },
  { key: "circle_new_non_academy_members", label: "Circle — new members NOT in Academy space", fields: ["academy_space_id"] },
  { key: "circle_active_academy_members", label: "Circle — active members in Academy space", fields: ["academy_space_id"] },
  { key: "monday_items_created_this_week", label: "Monday.com — items on a board this week (by status)", fields: ["board_id", "status_column_title", "status_values"] },
];

export default function MetricSourceDialog({ open, onOpenChange, metric, onSaved }) {
  const [connectorType, setConnectorType] = useState("");
  const [params, setParams] = useState({});
  const [discovery, setDiscovery] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!metric) return;
    setConnectorType(metric.source_type || "");
    setParams(metric.source_params || {});
  }, [metric]);

  useEffect(() => {
    if (!open) return;
    apiClient
      .get("/sync/discover")
      .then((r) => setDiscovery(r.data))
      .catch((e) => toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message));
  }, [open]);

  const connectorDef = useMemo(
    () => CONNECTORS.find((c) => c.key === connectorType),
    [connectorType]
  );

  const save = async () => {
    setSaving(true);
    try {
      const body = {
        source_type: connectorType || null,
        source_params: connectorType ? params : null,
      };
      await apiClient.patch(`/metrics/${metric.id}`, body);
      toast.success("Source saved");
      onOpenChange(false);
      onSaved?.();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    } finally {
      setSaving(false);
    }
  };

  const clearSource = async () => {
    setSaving(true);
    try {
      await apiClient.patch(`/metrics/${metric.id}`, {
        source_type: null,
        source_params: null,
      });
      toast.success("Source cleared");
      onOpenChange(false);
      onSaved?.();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    } finally {
      setSaving(false);
    }
  };

  if (!metric) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Configure data source — {metric.name}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <Label>Connector</Label>
            <Select value={connectorType} onValueChange={setConnectorType}>
              <SelectTrigger data-testid="source-connector-select"><SelectValue placeholder="Choose a source" /></SelectTrigger>
              <SelectContent>
                {CONNECTORS.map((c) => (
                  <SelectItem key={c.key || "none"} value={c.key || "__none__"}>
                    {c.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {connectorDef?.fields?.includes("show_id") && (
            <div>
              <Label>Transistor show</Label>
              <Select
                value={params.show_id ? String(params.show_id) : ""}
                onValueChange={(v) => setParams({ ...params, show_id: v })}
              >
                <SelectTrigger><SelectValue placeholder="Pick a show" /></SelectTrigger>
                <SelectContent>
                  {(discovery?.transistor_shows || []).map((s) => (
                    <SelectItem key={s.id} value={String(s.id)}>{s.title}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {connectorDef?.fields?.includes("tag_id") && (
            <div>
              <Label>ConvertKit tag</Label>
              <TagPicker
                tags={discovery?.convertkit_tags || []}
                value={params.tag_id}
                onChange={(v) => setParams({ ...params, tag_id: v })}
              />
            </div>
          )}

          {connectorDef?.fields?.includes("academy_space_id") && (
            <div>
              <Label>Circle — Academy space</Label>
              <Select
                value={params.academy_space_id ? String(params.academy_space_id) : ""}
                onValueChange={(v) => setParams({ ...params, academy_space_id: Number(v) })}
              >
                <SelectTrigger><SelectValue placeholder="Pick Academy space" /></SelectTrigger>
                <SelectContent>
                  {(discovery?.circle_spaces || []).map((s) => (
                    <SelectItem key={s.id} value={String(s.id)}>{s.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {connectorDef?.fields?.includes("board_id") && (
            <>
              <div>
                <Label>Monday.com board</Label>
                <BoardPicker
                  boards={discovery?.monday_boards || []}
                  value={params.board_id}
                  onChange={(v) => setParams({ ...params, board_id: v })}
                />
              </div>
              <div>
                <Label>Status column title (optional — defaults to any status column)</Label>
                <Input
                  value={params.status_column_title || ""}
                  onChange={(e) => setParams({ ...params, status_column_title: e.target.value })}
                  placeholder="e.g. Status"
                />
              </div>
              <div>
                <Label>Match status values (comma-separated — leave empty to count all items)</Label>
                <Input
                  value={(params.status_values || []).join(", ")}
                  onChange={(e) =>
                    setParams({
                      ...params,
                      status_values: e.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                  placeholder="e.g. Result Received, Interview"
                />
              </div>
            </>
          )}
        </div>

        <DialogFooter className="gap-2">
          {metric.source_type && (
            <Button variant="outline" onClick={clearSource} disabled={saving}>
              <Unplug className="w-4 h-4 mr-1" /> Clear source
            </Button>
          )}
          <Button onClick={save} disabled={saving || !connectorType || connectorType === "__none__"} style={{ backgroundColor: "var(--ayci-accent)" }}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TagPicker({ tags, value, onChange }) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return tags.slice(0, 30);
    return tags.filter((t) => (t.name || "").toLowerCase().includes(q)).slice(0, 60);
  }, [tags, query]);
  const selected = tags.find((t) => String(t.id) === String(value));

  return (
    <div className="space-y-2">
      <Input
        placeholder="Search tags…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {selected && (
        <div className="text-xs text-[var(--ayci-accent)]">Selected: {selected.name}</div>
      )}
      <div className="max-h-48 overflow-y-auto border border-[var(--ayci-border)] rounded-md ayci-scroll">
        {filtered.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => onChange(t.id)}
            className={
              "w-full text-left px-3 py-1.5 text-xs hover:bg-slate-50 " +
              (String(value) === String(t.id) ? "bg-slate-100 text-[var(--ayci-accent)]" : "")
            }
          >
            {t.name}
          </button>
        ))}
        {filtered.length === 0 && (
          <div className="px-3 py-2 text-xs text-[var(--ayci-ink-muted)]">No tags match.</div>
        )}
      </div>
    </div>
  );
}

function BoardPicker({ boards, value, onChange }) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return boards.slice(0, 40);
    return boards.filter((b) => (b.name || "").toLowerCase().includes(q)).slice(0, 60);
  }, [boards, query]);
  const selected = boards.find((b) => String(b.id) === String(value));

  return (
    <div className="space-y-2">
      <Input placeholder="Search boards…" value={query} onChange={(e) => setQuery(e.target.value)} />
      {selected && <div className="text-xs text-[var(--ayci-accent)]">Selected: {selected.name}</div>}
      <div className="max-h-48 overflow-y-auto border border-[var(--ayci-border)] rounded-md ayci-scroll">
        {filtered.map((b) => (
          <button
            key={b.id}
            type="button"
            onClick={() => onChange(b.id)}
            className={
              "w-full text-left px-3 py-1.5 text-xs hover:bg-slate-50 " +
              (String(value) === String(b.id) ? "bg-slate-100 text-[var(--ayci-accent)]" : "")
            }
          >
            {b.name}
          </button>
        ))}
      </div>
    </div>
  );
}

export { CONNECTORS };
