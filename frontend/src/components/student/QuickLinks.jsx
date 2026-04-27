import { ExternalLink, FileText, MessageSquare } from "lucide-react";

const PRIVATE_CHAT_COLUMN = "Private Chat Link";

export default function QuickLinks({ result }) {
  const monday = result?.monday?.data || {};
  const cols = monday.columns || {};
  const privateChatUrl = cols[PRIVATE_CHAT_COLUMN]?.text || null;
  const mondayUrl = monday.url;

  const links = [];
  if (privateChatUrl) {
    links.push({
      key: "private-chat",
      label: "Private chat",
      url: privateChatUrl,
      icon: MessageSquare,
      tone: "bg-violet-50 text-violet-700 border-violet-200",
    });
  }
  if (result?.drive?.found && result?.drive?.web_view_link) {
    links.push({
      key: "drive-doc",
      label: "Google Doc",
      url: result.drive.web_view_link,
      icon: FileText,
      tone: "bg-amber-50 text-amber-700 border-amber-200",
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
  // Drive doc link comes from PrivateDocCard's first render — for non-private
  // tiers there is no doc, so we surface it inside that card. For visibility
  // we add a "ghost" link here too if it's already cached.

  if (!links.length) return null;

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="student-quick-links">
      <span className="text-[10px] uppercase tracking-wider font-subhead text-[var(--ayci-ink-muted)] mr-2">
        <FileText className="w-3 h-3 inline mr-1" /> Quick links
      </span>
      {links.map((L) => (
        <a
          key={L.key}
          href={L.url}
          target="_blank"
          rel="noreferrer"
          className={`inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 border rounded-full hover:shadow-sm transition-shadow ${L.tone}`}
          data-testid={`quick-link-${L.key}`}
        >
          <L.icon className="w-3.5 h-3.5" />
          {L.label}
        </a>
      ))}
    </div>
  );
}
