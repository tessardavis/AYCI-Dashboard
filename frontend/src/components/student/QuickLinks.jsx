import { ExternalLink, FileText, MessageSquare, AlertTriangle } from "lucide-react";

const PRIVATE_CHAT_COLUMN = "Private Chat Link";

export default function QuickLinks({ result }) {
  const monday = result?.monday?.data || {};
  const cols = monday.columns || {};
  const privateChatUrl = cols[PRIVATE_CHAT_COLUMN]?.text || null;
  const mondayUrl = monday.url;

  const links = [];
  if (result?.drive?.found && result?.drive?.web_view_link) {
    const fuzzy = result.drive.needs_verification;
    links.push({
      key: "drive-doc",
      label: fuzzy ? "Google Doc · verify" : "Google Doc",
      url: result.drive.web_view_link,
      icon: fuzzy ? AlertTriangle : FileText,
      tone: fuzzy
        ? "bg-amber-50 text-amber-800 border-amber-300 ring-1 ring-amber-200"
        : "bg-amber-50 text-amber-700 border-amber-200",
      title: fuzzy
        ? `Closest match: "${result.drive.name}"${result.drive.match_score ? ` (${Math.round(result.drive.match_score * 100)}%)` : ""} — please verify`
        : result.drive.name,
    });
  }
  if (mondayUrl) {
    links.push({
      key: "monday",
      label: "Monday record",
      url: mondayUrl,
      icon: ExternalLink,
      tone: "bg-rose-50 text-rose-700 border-rose-200",
    });
  }

  if (!links.length && !privateChatUrl) return null;

  return (
    <div className="space-y-3" data-testid="student-quick-links">
      {/* Primary CTA — Private chat */}
      {privateChatUrl && (
        <a
          href={privateChatUrl}
          target="_blank"
          rel="noreferrer"
          data-testid="quick-link-private-chat"
          className="inline-flex items-center gap-2.5 px-5 py-3 bg-gradient-to-br from-violet-600 to-purple-600 hover:from-violet-700 hover:to-purple-700 text-white font-semibold rounded-lg shadow-sm hover:shadow-md transition-all border border-violet-700"
        >
          <MessageSquare className="w-5 h-5" />
          <span>Open private chat</span>
          <ExternalLink className="w-4 h-4 opacity-70" />
        </a>
      )}

      {links.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[10px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)] mr-2">
            <FileText className="w-3 h-3 inline mr-1" /> More
          </span>
          {links.map((L) => (
            <a
              key={L.key}
              href={L.url}
              target="_blank"
              rel="noreferrer"
              title={L.title}
              className={`inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 border rounded-full hover:shadow-sm transition-shadow ${L.tone}`}
              data-testid={`quick-link-${L.key}`}
            >
              <L.icon className="w-3.5 h-3.5" />
              {L.label}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
