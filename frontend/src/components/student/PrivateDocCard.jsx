import { useState } from "react";
import { Loader2, FileText, ExternalLink, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";

export default function PrivateDocCard({ email, name }) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [expanded, setExpanded] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get(`/students/drive-summary`, {
        params: { email, name },
        timeout: 90000,
      });
      setResult(data);
      if (data.error) toast.warning(data.error);
      else if (!data.found) toast.info(`No private-tier doc found (scanned ${data.candidates_scanned} files)`);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Failed to load doc");
    } finally {
      setLoading(false);
    }
  };

  if (!result && !loading) {
    return (
      <div className="bg-white border border-dashed border-[var(--ayci-border)] rounded-lg p-4 text-center">
        <Button
          onClick={load}
          variant="outline"
          className="text-sm"
          data-testid="load-private-doc-btn"
        >
          <Sparkles className="w-4 h-4 mr-2" />
          Load private-tier doc summary
        </Button>
        <div className="text-xs text-[var(--ayci-ink-muted)] mt-2">
          Fetches from Google Drive + AI-summarises (Claude Sonnet 4.5).
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-4 text-center text-sm text-[var(--ayci-ink-muted)]">
        <Loader2 className="w-4 h-4 animate-spin inline mr-2 text-[var(--ayci-teal)]" />
        Fetching doc and generating summary…
      </div>
    );
  }

  if (!result.found) {
    return (
      <div className="bg-slate-50 border border-[var(--ayci-border)] rounded-lg p-4 text-sm">
        <div className="flex items-center gap-2 text-[var(--ayci-ink-muted)]">
          <FileText className="w-4 h-4" />
          No private-tier doc found for this student.
        </div>
        <div className="text-xs text-[var(--ayci-ink-muted)] mt-1">
          Scanned {result.candidates_scanned} files in the Drive folder.
        </div>
      </div>
    );
  }

  return (
    <div
      className="bg-gradient-to-br from-violet-50 to-white border border-violet-200 rounded-lg p-4 shadow-sm"
      data-testid="private-doc-summary"
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-violet-100 flex items-center justify-center">
            <Sparkles className="w-4 h-4 text-violet-600" />
          </div>
          <div>
            <div className="font-display font-semibold text-[var(--ayci-ink)]">
              {result.file.name}
            </div>
            <div className="text-[11px] text-[var(--ayci-ink-muted)]">
              Private-tier doc · AI-summarised
              {result.cached && " · cached"}
              {result.file.modifiedTime && ` · updated ${new Date(result.file.modifiedTime).toLocaleDateString("en-GB")}`}
            </div>
          </div>
        </div>
        {result.file.web_view_link && (
          <a
            href={result.file.web_view_link}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-[var(--ayci-teal)] hover:underline inline-flex items-center gap-1"
          >
            Open doc <ExternalLink className="w-3 h-3" />
          </a>
        )}
      </div>

      {result.error && (
        <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2 mb-3">
          {result.error}
        </div>
      )}

      {result.summary && (
        <div className="text-sm text-[var(--ayci-ink)]">
          <div
            className={
              "whitespace-pre-wrap prose prose-sm max-w-none " +
              (expanded ? "" : "line-clamp-[18]")
            }
          >
            {renderMarkdown(result.summary)}
          </div>
          {result.summary.length > 400 && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-xs text-[var(--ayci-teal)] hover:underline mt-1"
            >
              {expanded ? "Show less" : "Show more"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// Super-light markdown renderer: **bold** → <strong>
function renderMarkdown(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) {
      return (
        <strong key={i} className="font-display font-semibold text-[var(--ayci-ink)]">
          {p.slice(2, -2)}
        </strong>
      );
    }
    return <span key={i}>{p}</span>;
  });
}
