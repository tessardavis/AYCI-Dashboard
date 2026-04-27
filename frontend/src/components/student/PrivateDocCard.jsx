import { useState } from "react";
import { Loader2, FileText, ExternalLink, Sparkles, AlertTriangle } from "lucide-react";
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

      {result.match?.needs_verification && (
        <div
          className="text-xs bg-amber-50 border border-amber-200 text-amber-900 rounded p-2.5 mb-3 flex items-start gap-2"
          data-testid="fuzzy-match-warning"
        >
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            <div className="font-display font-semibold">
              Possible match — please verify before using
            </div>
            <div className="mt-0.5 text-amber-800">
              Looking for{" "}
              <strong className="font-display">
                "{result.match.searched_name}"
              </strong>{" "}
              but the closest doc is{" "}
              <strong className="font-display">
                "{result.file.name}"
              </strong>
              {result.match.score && (
                <span className="opacity-70">
                  {" "}
                  ({Math.round(result.match.score * 100)}% similar
                  {result.match.reason === "lastname" ? ", surname only" : ""})
                </span>
              )}
              . Open the doc to confirm it's the right student.
            </div>
            {result.match.other_candidates?.length > 0 && (
              <div className="mt-1.5 text-[11px] text-amber-700">
                Other near-matches:{" "}
                {result.match.other_candidates
                  .map((c) => `"${c.name}" (${Math.round(c.score * 100)}%)`)
                  .join(", ")}
              </div>
            )}
          </div>
        </div>
      )}

      {result.error && (
        <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2 mb-3">
          {result.error}
        </div>
      )}

      {result.summary && (
        <div className="text-sm text-[var(--ayci-ink)]">
          <div
            className={
              "space-y-1 " + (expanded ? "" : "max-h-96 overflow-hidden")
            }
          >
            {renderMarkdown(result.summary)}
          </div>
          {result.summary.length > 400 && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-xs text-[var(--ayci-teal)] hover:underline mt-2"
            >
              {expanded ? "Show less" : "Show more"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// Light markdown renderer: handles **bold**, # headers, - bullets, line breaks
function renderMarkdown(text) {
  const lines = text.split("\n");
  return lines.map((line, i) => {
    let className = "";
    let content = line;
    if (/^#{1,3}\s/.test(line)) {
      // Header — strip the # and bold it
      content = line.replace(/^#{1,3}\s*/, "");
      className = "font-display font-bold text-base text-[var(--ayci-ink)] mt-2 first:mt-0";
    } else if (/^[-*]\s/.test(line)) {
      content = line.replace(/^[-*]\s*/, "• ");
      className = "ml-2";
    }
    // Inline **bold**
    const parts = content.split(/(\*\*[^*]+\*\*)/);
    return (
      <div key={i} className={className}>
        {parts.map((p, j) => {
          if (p.startsWith("**") && p.endsWith("**")) {
            return (
              <strong key={j} className="font-display font-semibold text-[var(--ayci-ink)]">
                {p.slice(2, -2)}
              </strong>
            );
          }
          return <span key={j}>{p}</span>;
        })}
      </div>
    );
  });
}
