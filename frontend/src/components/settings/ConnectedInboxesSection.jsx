import { useEffect, useState } from "react";
import {
  Mail,
  Plus,
  Trash2,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Loader2,
  ExternalLink,
} from "lucide-react";
import { toast } from "sonner";
import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";

/**
 * Settings → Connected Inboxes (admin only).
 *
 * Lets admins connect Gmail accounts via per-inbox OAuth. Each connected
 * inbox is polled every 15 min by the backend; new inbound emails become
 * tickets, replies are appended to existing tickets via Gmail threadId.
 */
export default function ConnectedInboxesSection({ isAdmin }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [ingestInbound, setIngestInbound] = useState(false);

  const load = async () => {
    try {
      const { data } = await apiClient.get("/oauth/gmail/status");
      setData(data);
    } catch (err) {
      toast.error(
        formatApiErrorDetail(err.response?.data?.detail) || "Failed to load inboxes",
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  // Listen for popup → opener message after OAuth completes
  useEffect(() => {
    const onMsg = (e) => {
      if (e.data?.type !== "gmail-oauth") return;
      if (e.data.success) {
        toast.success(e.data.message || "Inbox connected");
        load();
      } else {
        toast.error(e.data.message || "OAuth failed");
      }
      setConnecting(false);
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, []);

  const handleConnect = async () => {
    setConnecting(true);
    try {
      const { data } = await apiClient.post("/oauth/gmail/start", null, {
        params: { return_to: "/settings", ingest_inbound: ingestInbound },
      });
      const url = data.authorize_url;
      const w = 520;
      const h = 640;
      const left = window.screenX + (window.outerWidth - w) / 2;
      const top = window.screenY + (window.outerHeight - h) / 2;
      window.open(
        url,
        "gmail-oauth",
        `width=${w},height=${h},left=${left},top=${top}`,
      );
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(formatApiErrorDetail(detail) || "Failed to start OAuth");
      setConnecting(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    try {
      const { data } = await apiClient.post("/oauth/gmail/sync");
      const totals = `${data.created || 0} new, ${data.updated || 0} updated · scanned ${data.scanned || 0}`;
      if (data.errors > 0) {
        toast.warning(`Synced with ${data.errors} error(s) — ${totals}`);
      } else {
        toast.success(`Sync complete — ${totals}`);
      }
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const handleRemove = async (inbox) => {
    if (!window.confirm(`Disconnect ${inbox.email}? Existing tickets stay; future emails won't be ingested.`)) {
      return;
    }
    try {
      await apiClient.delete(`/oauth/gmail/inboxes/${inbox.id}`);
      toast.success(`Disconnected ${inbox.email}`);
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Disconnect failed");
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-[var(--ayci-ink-muted)]">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading…
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="connected-inboxes-section">
      <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-3">
            <div className="bg-sky-50 border border-sky-200 rounded-md p-2">
              <Mail className="w-5 h-5 text-sky-700" />
            </div>
            <div>
              <h3 className="font-display font-bold text-[var(--ayci-ink)]">
                My Gmail Inbox
              </h3>
              <p className="text-xs text-[var(--ayci-ink-muted)] mt-0.5 max-w-xl">
                Connect your own Gmail account so ticket replies go out from
                your address. Optionally also "ingest inbound" — incoming
                emails (from non-team senders) become Support Tickets every
                15 min, with reply threads appended automatically.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleSync}
              disabled={syncing || (data?.inboxes || []).length === 0}
              data-testid="inboxes-sync-now"
            >
              {syncing ? (
                <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
              ) : (
                <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
              )}
              Sync now
            </Button>
            <Button
              size="sm"
              onClick={handleConnect}
              disabled={!data?.configured || connecting}
              data-testid="inboxes-connect-button"
            >
              {connecting ? (
                <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
              ) : (
                <Plus className="w-3.5 h-3.5 mr-1.5" />
              )}
              Connect Gmail
            </Button>
          </div>
        </div>

        <label className="mt-3 flex items-start gap-2 text-xs text-[var(--ayci-ink-muted)] cursor-pointer">
          <input
            type="checkbox"
            checked={ingestInbound}
            onChange={(e) => setIngestInbound(e.target.checked)}
            className="mt-0.5"
            data-testid="inboxes-ingest-inbound"
          />
          <span>
            <span className="font-semibold text-[var(--ayci-ink)]">Ingest inbound emails as tickets</span>
            <span className="block">Tick this if your inbox is a shared support address (e.g. <code>support@…</code>). Most personal inboxes should leave this off.</span>
          </span>
        </label>

        {!data?.configured && (
          <div className="mt-4 bg-amber-50 border border-amber-200 rounded-md p-3 text-xs text-amber-900">
            <div className="font-semibold mb-1 flex items-center gap-1.5">
              <AlertCircle className="w-3.5 h-3.5" />
              Gmail integration not yet configured
            </div>
            Backend env vars <code className="bg-amber-100 px-1 rounded">GOOGLE_CLIENT_ID</code> and{" "}
            <code className="bg-amber-100 px-1 rounded">GOOGLE_CLIENT_SECRET</code> must be set in{" "}
            <code className="bg-amber-100 px-1 rounded">/app/backend/.env</code>. See{" "}
            <a
              href="https://console.cloud.google.com"
              target="_blank"
              rel="noreferrer"
              className="underline font-semibold inline-flex items-center gap-0.5"
            >
              Google Cloud Console <ExternalLink className="w-3 h-3" />
            </a>
            .
          </div>
        )}

        {(data?.inboxes || []).length === 0 ? (
          <div className="mt-5 text-sm text-[var(--ayci-ink-muted)] text-center py-8 border border-dashed border-slate-200 rounded-md">
            You haven't connected a Gmail inbox yet.
            {data?.configured && " Click 'Connect Gmail' to authorise your account."}
          </div>
        ) : (
          <div className="mt-5 divide-y divide-slate-100 border border-slate-200 rounded-md overflow-hidden">
            {data.inboxes.map((ib) => (
              <InboxRow key={ib.id} inbox={ib} onRemove={() => handleRemove(ib)} />
            ))}
          </div>
        )}

        {data?.is_admin && (data?.all_inboxes || []).length > (data?.inboxes || []).length && (
          <div className="mt-4 text-xs text-[var(--ayci-ink-muted)]">
            <details>
              <summary className="cursor-pointer font-semibold">
                Admin · all team inboxes ({(data?.all_inboxes || []).length})
              </summary>
              <div className="mt-2 divide-y divide-slate-100 border border-slate-200 rounded-md overflow-hidden">
                {data.all_inboxes.map((ib) => (
                  <InboxRow key={ib.id} inbox={ib} onRemove={() => handleRemove(ib)} adminView />
                ))}
              </div>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}

function InboxRow({ inbox, onRemove, adminView }) {
  const last = inbox.last_sync_at
    ? new Date(inbox.last_sync_at).toLocaleString("en-GB", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Europe/London",
      })
    : null;
  const status = inbox.last_sync_status || (last ? "ok" : (inbox.ingest_inbound ? "pending" : "send-only"));
  const isError = status && status.startsWith && (status.startsWith("auth_") || status.startsWith("api_"));
  return (
    <div
      className="flex items-center gap-3 px-4 py-3 text-sm"
      data-testid={`inbox-row-${inbox.id}`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 font-semibold text-[var(--ayci-ink)] truncate">
          <Mail className="w-3.5 h-3.5 text-[var(--ayci-ink-muted)] flex-shrink-0" />
          <span className="truncate">{inbox.email}</span>
          {inbox.ingest_inbound ? (
            <span className="inline-flex items-center text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-sky-50 text-sky-800 border border-sky-200 font-bold">
              Ingest
            </span>
          ) : (
            <span className="inline-flex items-center text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-slate-50 text-slate-700 border border-slate-200 font-bold">
              Send-only
            </span>
          )}
        </div>
        <div className="text-xs text-[var(--ayci-ink-muted)] mt-0.5 flex items-center gap-3 flex-wrap">
          <span>
            {inbox.tickets_created || 0} created · {inbox.tickets_updated || 0} updated
          </span>
          {last && <span>Last sync {last}</span>}
          {adminView && inbox.user_id && <span className="opacity-60">user: {inbox.user_id.slice(0, 8)}</span>}
        </div>
      </div>
      <div className="flex items-center gap-1.5">
        {isError ? (
          <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 bg-rose-50 text-rose-700 rounded border border-rose-200">
            <AlertCircle className="w-3 h-3" />
            Error
          </span>
        ) : status === "ok" ? (
          <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 bg-emerald-50 text-emerald-700 rounded border border-emerald-200">
            <CheckCircle2 className="w-3 h-3" />
            Healthy
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 bg-slate-50 text-slate-600 rounded border border-slate-200">
            {status === "send-only" ? "Send-only" : "Pending"}
          </span>
        )}
        <button
          onClick={onRemove}
          className="text-rose-600 hover:text-rose-800 p-1.5 rounded hover:bg-rose-50 transition-colors"
          data-testid={`inbox-remove-${inbox.id}`}
          title="Disconnect inbox"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
