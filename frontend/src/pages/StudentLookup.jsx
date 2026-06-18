import { useEffect, useState, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { Search, Loader2, RefreshCw, ExternalLink, Pencil, Check, X, Copy } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { tallyPrefillUrl } from "@/lib/tally";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import StudentPlatformCard from "@/components/StudentPlatformCard";
import CircleCard from "@/components/student/CircleCard";
import CalendlyCard from "@/components/student/CalendlyCard";
import TallyCard from "@/components/student/TallyCard";
import PrivateDocCard from "@/components/student/PrivateDocCard";
import CoachSummary from "@/components/student/CoachSummary";
import QuickLinks from "@/components/student/QuickLinks";
import EngagementBar from "@/components/student/EngagementBar";
import SignupHistoryCard from "@/components/student/SignupHistoryCard";

export default function StudentLookup() {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState(""); // email we searched for (persists across typing)
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [refreshingCache, setRefreshingCache] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [searchingNames, setSearchingNames] = useState(false);
  const debounceRef = useRef(null);
  const [searchParams] = useSearchParams();

  // Auto-run lookup when an `?email=` query param is provided (e.g. from at-risk page)
  // or auto-fill the search box when only `?name=` is provided (e.g. from a Circle DM
  // ticket where we only have the student's display name, not their email).
  useEffect(() => {
    const emailParam = searchParams.get("email");
    const nameParam = searchParams.get("name");
    if (emailParam && emailParam !== query) {
      setSearch(emailParam);
      runLookupForEmail(emailParam);
    } else if (!emailParam && nameParam && nameParam !== search) {
      // Pre-fill the input — the debounced name-search effect will fire
      // suggestions automatically so the coach can pick the right student.
      setSearch(nameParam);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // Set to true the moment the coach picks a suggestion (or focuses out).
  // Prevents the dropdown from popping back open when the input text is
  // programmatically set to the picked name — which would re-trigger the
  // debounced name-search effect and re-show the suggestion list right
  // when the unified lookup is loading.
  const suppressSuggestionsRef = useRef(false);

  // Debounced name autocomplete (only when input doesn't look like an email)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const trimmed = search.trim();
    if (trimmed.length < 2 || trimmed.includes("@")) {
      setSuggestions([]);
      return;
    }
    if (suppressSuggestionsRef.current) {
      // Don't fire suggestions for a programmatic input update right after a
      // pick. The user can clear the input or type a new character to re-arm.
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setSearchingNames(true);
      try {
        const { data } = await apiClient.get(`/students/name-search`, {
          params: { q: trimmed, limit: 8 },
          // 30s — the first name-search after a backend restart has to read
          // a 1.7MB Mongo doc; subsequent calls are in-memory.
          timeout: 30000,
        });
        setSuggestions(data || []);
        setShowSuggestions(true);
      } catch {
        setSuggestions([]);
      } finally {
        setSearchingNames(false);
      }
    }, 300);
    return () => debounceRef.current && clearTimeout(debounceRef.current);
  }, [search]);

  const runLookupForEmail = async (email, name = null) => {
    setLoading(true);
    setResult(null);
    setQuery(email);
    setShowSuggestions(false);
    try {
      const { data } = await apiClient.get(`/students/lookup`, {
        params: name ? { email, name } : { email },
        timeout: 90000,
      });
      setResult(data);
      const hits = ["monday", "stripe", "convertkit", "circle", "calendly"].filter(
        (k) => data[k]?.found,
      );
      if (hits.length === 0) {
        toast.info("No data found on any platform for this email");
      } else {
        toast.success(`Found on ${hits.length} of 5 platforms`);
      }
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Lookup failed");
    } finally {
      setLoading(false);
    }
  };

  const runLookup = async (e) => {
    e?.preventDefault();
    const trimmed = search.trim().toLowerCase();
    if (!trimmed) {
      toast.error("Enter an email or name to search");
      return;
    }
    if (trimmed.includes("@")) {
      await runLookupForEmail(trimmed);
    } else if (suggestions.length > 0) {
      // Pick top match
      const top = suggestions[0];
      await runLookupForEmail(top.email, top.name);
    } else {
      toast.info("No matching student found by name");
    }
  };

  const pickSuggestion = (s) => {
    suppressSuggestionsRef.current = true;
    setSearch(s.name || s.email);
    setShowSuggestions(false);
    setSuggestions([]);
    runLookupForEmail(s.email, s.name);
  };

  // Hover-prefetch: warm the unified-lookup endpoint for the hovered
  // suggestion so that clicking it returns instantly. Session-scoped dedupe
  // so we don't re-fire for the same email.
  const prefetchedRef = useRef(new Set());
  const prefetchHoverRef = useRef(null);
  const prefetchSuggestion = (email) => {
    clearTimeout(prefetchHoverRef.current);
    if (!email || prefetchedRef.current.has(email)) return;
    prefetchHoverRef.current = setTimeout(() => {
      prefetchedRef.current.add(email);
      apiClient
        .get(`/students/lookup`, { params: { email }, timeout: 30000 })
        .catch(() => prefetchedRef.current.delete(email));
    }, 200);
  };
  const cancelPrefetch = () => clearTimeout(prefetchHoverRef.current);

  const refreshCircleCache = async () => {
    setRefreshingCache(true);
    try {
      const { data } = await apiClient.post(`/students/circle-cache/refresh`, null, {
        timeout: 120000,
      });
      toast.success(`Circle cache refreshed — ${data.member_count} members`);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Cache refresh failed");
    } finally {
      setRefreshingCache(false);
    }
  };

  // Derive a "student header" from any platform that has a name + key facts
  const header = (() => {
    if (!result) return null;
    // Monday is our source-of-truth for the student's full name (synced from
    // their Tally signup form). Circle / ConvertKit often store just the
    // first name so prefer Monday first.
    const name =
      result.monday?.data?.name ||
      result.circle?.data?.name ||
      result.convertkit?.data?.first_name ||
      result.stripe?.data?.customers?.[0]?.name ||
      null;
    const avatar = result.circle?.data?.avatar_url;

    // Pull interview details with sensible fallbacks across platforms.
    const mondayCols = result.monday?.data?.columns || {};
    const tally = result.tally || {};
    // The most-recently-SUBMITTED Tally entry is authoritative on reschedules
    // (Tessa's rule). history is sorted by date upstream, so re-sort by
    // submitted_at here to honour "latest submission wins".
    const tallyHist =
      (tally.history || [])
        .slice()
        .sort((a, b) => (b.submitted_at || "").localeCompare(a.submitted_at || ""))[0] || {};

    // Prefer the latest Tally date over the (stale, sync-overwritten) Monday
    // column; fall back to Monday only when there's no Tally submission.
    const interviewDate =
      tallyHist.date ||
      (mondayCols["Interview Date"]?.text || "").trim() ||
      null;
    const kajabiDate = (mondayCols["Kajabi Interview Date"]?.text || "").trim();
    const interviewType =
      (mondayCols["Interview Type"]?.text || "").trim() ||
      tally.type ||
      tallyHist.type ||
      null;
    const speciality =
      (mondayCols["Speciality"]?.text || "").trim() ||
      (mondayCols["Specialty"]?.text || "").trim() ||
      tallyHist.speciality ||
      null;
    const hospital =
      (mondayCols["Hospital"]?.text || "").trim() ||
      tallyHist.hospital ||
      null;
    const tier = (mondayCols["Tier"]?.text || "").trim();

    return {
      name,
      avatar,
      email: result.email,
      interviewDate,
      kajabiDate,
      interviewType,
      speciality,
      hospital,
      tier,
    };
  })();

  return (
    <div className="p-3 sm:p-6 lg:p-8 space-y-4 sm:space-y-6" data-testid="student-lookup-page">
      <div>
        <div className="text-[10px] sm:text-[11px] font-display font-semibold tracking-[0.2em] sm:tracking-[0.25em] uppercase text-[var(--ayci-teal)]">
          Unified view
        </div>
        <h1 className="text-2xl sm:text-3xl lg:text-4xl font-display font-bold text-[var(--ayci-ink)] mt-1">
          Student Lookup
        </h1>
        <p className="text-[var(--ayci-ink-muted)] text-xs sm:text-sm mt-1 max-w-xl hidden sm:block">
          Search any student by <strong>email or name</strong> to see a unified profile pulled live from Monday.com,
          Circle, Stripe, ConvertKit and Calendly.
        </p>
      </div>

      <form
        onSubmit={runLookup}
        className="flex flex-wrap items-stretch sm:items-center gap-2 sm:gap-3 bg-white border border-[var(--ayci-border)] rounded-lg p-3 sm:p-4 shadow-sm"
      >
        <div className="relative flex-1 w-full sm:min-w-[320px] sm:w-auto">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[var(--ayci-ink-muted)]" />
          <Input
            value={search}
            onChange={(e) => {
              // Any user typing re-arms suggestions (so they can pick a
              // different student after a previous lookup).
              suppressSuggestionsRef.current = false;
              setSearch(e.target.value);
            }}
            onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
            placeholder="Email or name…"
            className="pl-9 h-11"
            data-testid="student-lookup-input"
            autoFocus
          />
          {searchingNames && (
            <Loader2 className="w-4 h-4 absolute right-3 top-1/2 -translate-y-1/2 text-[var(--ayci-ink-muted)] animate-spin" />
          )}
          {showSuggestions && suggestions.length > 0 && (
            <div
              className="absolute top-full left-0 right-0 mt-1 bg-white border border-[var(--ayci-border)] rounded-lg shadow-lg z-10 max-h-72 overflow-y-auto"
              data-testid="name-suggestions"
            >
              {suggestions.map((s) => (
                <button
                  key={s.email}
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => pickSuggestion(s)}
                  onMouseEnter={() => prefetchSuggestion(s.email)}
                  onMouseLeave={cancelPrefetch}
                  onFocus={() => prefetchSuggestion(s.email)}
                  className="w-full text-left px-3 py-2 hover:bg-slate-50 border-b border-[var(--ayci-border)] last:border-b-0 flex items-center gap-2"
                  data-testid={`suggestion-${s.email}`}
                >
                  {s.avatar_url ? (
                    <img src={s.avatar_url} alt="" className="w-7 h-7 rounded-full object-cover" />
                  ) : (
                    <div className="w-7 h-7 rounded-full bg-slate-100 flex items-center justify-center text-[10px] font-semibold text-slate-500">
                      {(s.name || s.email).slice(0, 2).toUpperCase()}
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm text-[var(--ayci-ink)] truncate">
                      {s.name || "—"}
                    </div>
                    <div className="text-xs text-[var(--ayci-ink-muted)] truncate">{s.email}</div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
        <Button
          type="submit"
          disabled={loading}
          className="bg-[var(--ayci-teal)] hover:bg-[var(--ayci-teal-dark)] text-white h-11 px-5 flex-1 sm:flex-none"
          data-testid="student-lookup-search-button"
        >
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" /> Searching…
            </>
          ) : (
            <>
              <Search className="w-4 h-4 mr-2" /> Search
            </>
          )}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={refreshCircleCache}
          disabled={refreshingCache}
          className="h-11 hidden sm:inline-flex"
          title="Refresh cached Circle members list (runs daily automatically)"
          data-testid="student-lookup-refresh-cache"
        >
          {refreshingCache ? (
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
          ) : (
            <RefreshCw className="w-4 h-4 mr-2" />
          )}
          Refresh Circle cache
        </Button>
      </form>

      {loading && !result && (
        <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-8 text-center text-[var(--ayci-ink-muted)]">
          <Loader2 className="w-6 h-6 animate-spin mx-auto mb-3 text-[var(--ayci-teal)]" />
          Querying Monday, Circle, Stripe, ConvertKit, and Calendly in parallel…
        </div>
      )}

      {result && (
        <>
          {/* Identity header */}
          <StudentHeaderCard
            header={header}
            query={query}
            result={result}
            onNameSaved={(newName) => {
              // Optimistically update the in-place result so the header reflects
              // the saved name immediately, then re-fetch in the background to
              // pick up any downstream changes (Circle cache invalidation etc.).
              setResult((prev) => prev && prev.monday?.data
                ? { ...prev, monday: { ...prev.monday, data: { ...prev.monday.data, name: newName } } }
                : prev);
              // Bust the server-side cache and re-fetch on next tab visit.
              apiClient
                .get(`/students/lookup`, { params: { email: query, refresh: true }, timeout: 30000 })
                .then(({ data }) => setResult(data))
                .catch(() => {});
            }}
          />

          {/* Coach summary — at-a-glance tier + calls/videos remaining + last call */}
          <CoachSummary result={result} />

          {/* Cohort engagement progress — 5 Circle milestone tags */}
          <EngagementBar circle={result.circle} />

          {/* Quick links — private chat + Google Doc */}
          <QuickLinks result={result} />

          {/* Team notes + pre-filled Tally form link */}
          <StudentNotesCard email={result.email} fallbackName={header?.name || result.monday?.data?.name || query} />


          {/* Private-tier Google Doc summary (only for non-pure-Academy students) */}
          {isPrivateTier(result.monday?.data) && (
            <PrivateDocCard
              email={result.email}
              name={header?.name || result.monday?.data?.name || query}
              initialResult={result.drive_summary}
            />
          )}

          {/* Platform cards grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 sm:gap-5">
            <StudentPlatformCard
              title="Calendly — Calls"
              platform="calendly"
              state={result.calendly}
              accent="#006bff"
            >
              <CalendlyCard data={result.calendly?.data} />
            </StudentPlatformCard>

            <StudentPlatformCard
              title="Tally — Past interviews"
              platform="tally"
              state={{
                found: (result.tally?.history_count || 0) > 0,
                data: result.tally,
                error: null,
              }}
              accent="#FF7A1A"
            >
              <TallyCard data={result.tally} />
            </StudentPlatformCard>

            <StudentPlatformCard
              title="Signup history & cohorts"
              platform="stripe"
              state={{
                found: (result.stripe?.data?.charges?.length || 0) > 0
                  || (result.circle?.data?.member_tags?.length || 0) > 0,
                data: result,
                error: null,
              }}
              accent="#635bff"
            >
              <SignupHistoryCard
                stripe={result.stripe?.data}
                circle={result.circle?.data}
              />
            </StudentPlatformCard>

            <StudentPlatformCard
              title="Circle — Community"
              platform="circle"
              state={result.circle}
              accent="#7c3aed"
            >
              <CircleCard data={result.circle?.data} />
            </StudentPlatformCard>
          </div>
        </>
      )}
    </div>
  );
}

function StudentNotesCard({ email, fallbackName }) {
  const [row, setRow] = useState(null);
  const [note, setNote] = useState("");
  const [otherEmails, setOtherEmails] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!email) return;
    let alive = true;
    setLoading(true);
    apiClient
      .get("/students-db", { params: { q: email, limit: 10 } })
      .then(({ data }) => {
        if (!alive) return;
        const items = data.items || [];
        const lc = email.toLowerCase();
        const match =
          items.find((r) => (r.email || "").toLowerCase() === lc || (r.circle_email || "").toLowerCase() === lc) ||
          items[0] ||
          null;
        setRow(match);
        setNote((match && match.coach_notes) || "");
        setOtherEmails((match && match.other_emails) || "");
      })
      .catch(() => alive && setRow(null))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [email]);

  const save = async () => {
    if (!row?._id) return;
    setSaving(true);
    try {
      const { data } = await apiClient.patch(`/students-db/${row._id}`, {
        coach_notes: note || null,
        other_emails: otherEmails.trim() || null,
      });
      setRow(data);
      setNote(data.coach_notes || "");
      setOtherEmails(data.other_emails || "");
      toast.success("Saved");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Couldn't save");
    } finally {
      setSaving(false);
    }
  };

  // Name parts for the pre-filled Tally link: prefer the DB row, fall back to
  // splitting the display name.
  const parts = String(fallbackName || "").trim().split(/\s+/);
  const first = (row && row.first_name) || parts[0] || "";
  const last = (row && row.surname) || (parts.length > 1 ? parts.slice(1).join(" ") : "");
  const tallyUrl = tallyPrefillUrl({ contactId: row && row._id, first, last, email, speciality: row && row.speciality });

  const dirty =
    (note || "") !== ((row && row.coach_notes) || "") ||
    (otherEmails || "") !== ((row && row.other_emails) || "");

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="font-display text-sm font-extrabold text-[var(--ayci-ink)] mb-2">Notes & interview-date form</div>

      {/* Pre-filled "report interview date" Tally link to copy + send to the student */}
      <div className="mb-3">
        <div className="text-[10px] uppercase tracking-wider font-bold text-[var(--ayci-ink-muted)] mb-1">
          Pre-filled interview-date form link (copy &amp; send)
        </div>
        <div className="flex items-center gap-2">
          <input
            readOnly
            value={tallyUrl}
            onFocus={(e) => e.target.select()}
            className="flex-1 min-w-0 rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5 text-[11px] text-slate-700"
          />
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              (navigator.clipboard?.writeText(tallyUrl) || Promise.reject())
                .then(() => toast.success("Tally link copied — ready to send"))
                .catch(() => toast.error("Couldn't copy — select the text and copy manually"));
            }}
          >
            <Copy className="w-4 h-4 mr-1" /> Copy
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-[12px] text-[var(--ayci-ink-muted)]">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading notes…
        </div>
      ) : !row?._id ? (
        <div className="text-[12px] text-[var(--ayci-ink-muted)]">
          This student isn't in the Students DB yet, so notes can't be saved. The Tally link above still works.
        </div>
      ) : (
        <>
          <div className="mb-3">
            <div className="text-[10px] uppercase tracking-wider font-bold text-[var(--ayci-ink-muted)] mb-1">
              Other emails (Calendly/Stripe/Circle booked under — comma-separated)
            </div>
            <input
              value={otherEmails}
              onChange={(e) => setOtherEmails(e.target.value)}
              placeholder="e.g. henrymurphy@hotmail.co.uk"
              className="w-full rounded-md border border-slate-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-sky-200"
            />
            <div className="text-[10px] text-[var(--ayci-ink-muted)] mt-1">
              Add any other address this student uses — the lookup then matches their Calendly, Stripe, Circle and Tally under it too.
            </div>
          </div>
          <textarea
            rows={4}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Add notes about this student — visible to anyone with student access."
            className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-200"
          />
          <div className="flex items-center justify-end mt-2">
            <Button size="sm" onClick={save} disabled={saving || !dirty}>
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Check className="w-4 h-4 mr-2" />}
              {dirty ? "Save changes" : "Saved"}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

function StudentHeaderCard({ header, query, result, onNameSaved }) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  // Derive interview-date status
  let interviewBlock = null;
  if (header?.interviewDate) {
    const d = new Date(header.interviewDate);
    const isValid = !isNaN(d.getTime());
    if (isValid) {
      d.setHours(0, 0, 0, 0);
      const diffDays = Math.round((d - today) / 86400000);
      const past = diffDays < 0;
      const tone = past
        ? "bg-slate-100 border-slate-200 text-slate-700"
        : diffDays <= 7
        ? "bg-rose-50 border-rose-300 text-rose-900"
        : diffDays <= 21
        ? "bg-amber-50 border-amber-300 text-amber-900"
        : "bg-emerald-50 border-emerald-300 text-emerald-800";
      const niceDate = d.toLocaleDateString("en-GB", {
        weekday: "short",
        day: "numeric",
        month: "long",
        year: "numeric",
      });
      const subtitle = past
        ? `${Math.abs(diffDays)} day${Math.abs(diffDays) === 1 ? "" : "s"} ago`
        : diffDays === 0
        ? "Today"
        : diffDays === 1
        ? "Tomorrow"
        : `In ${diffDays} days`;
      interviewBlock = { tone, niceDate, subtitle, past, diffDays };
    }
  }

  const interviewType = header?.interviewType
    ? header.interviewType.charAt(0).toUpperCase() + header.interviewType.slice(1).toLowerCase()
    : null;

  return (
    <div
      className="bg-white border border-[var(--ayci-border)] rounded-lg p-4 sm:p-5 shadow-sm space-y-4"
      data-testid="student-header-card"
    >
      <div className="flex items-center gap-3 sm:gap-4 flex-wrap">
        {header?.avatar ? (
          <img
            src={header.avatar}
            alt={header.name || "Avatar"}
            className="w-12 h-12 sm:w-14 sm:h-14 rounded-full object-cover border border-[var(--ayci-border)] shrink-0"
          />
        ) : (
          <div className="w-12 h-12 sm:w-14 sm:h-14 rounded-full bg-slate-100 flex items-center justify-center text-slate-500 font-display font-bold shrink-0">
            {(header?.name || query).slice(0, 2).toUpperCase()}
          </div>
        )}
        <div className="flex-1 min-w-0">
          <StudentNameEditor
            currentName={header?.name || "Unknown student"}
            mondayItemId={result?.monday?.data?.id}
            onSaved={onNameSaved}
          />
          <div className="text-xs sm:text-sm text-[var(--ayci-ink-muted)] flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="break-all">{query}</span>
            {header?.tier && (
              <>
                <span className="text-[var(--ayci-ink-muted)] opacity-60 hidden sm:inline">·</span>
                <span className="font-display font-semibold text-[var(--ayci-teal)]">
                  {header.tier}
                </span>
              </>
            )}
          </div>
        </div>
        <div className="w-full sm:w-auto hidden sm:block">
          <PlatformBadges result={result} />
        </div>
      </div>

      {/* Big & clear interview / specialty banner */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2 sm:gap-3" data-testid="student-interview-summary">
        {/* Interview date */}
        {interviewBlock ? (
          <div
            className={`rounded-lg border px-3 py-2.5 sm:px-4 sm:py-3 col-span-2 md:col-span-1 ${interviewBlock.tone}`}
            data-testid="student-interview-date"
          >
            <div className="text-[10px] uppercase tracking-widest font-display font-bold opacity-70">
              Interview
            </div>
            <div className="font-display font-bold text-lg leading-tight mt-0.5">
              {interviewBlock.niceDate}
            </div>
            <div className="text-xs mt-0.5 font-semibold">{interviewBlock.subtitle}</div>
          </div>
        ) : header?.kajabiDate ? (
          <div
            className="rounded-lg border bg-slate-50 border-slate-200 text-slate-700 px-3 py-2.5 sm:px-4 sm:py-3 col-span-2 md:col-span-1"
            data-testid="student-interview-date"
          >
            <div className="text-[10px] uppercase tracking-widest font-display font-bold opacity-70">
              Interview (rough)
            </div>
            <div className="font-display font-bold text-lg leading-tight mt-0.5">
              {header.kajabiDate}
            </div>
            <div className="text-xs mt-0.5 italic opacity-70">No exact date set yet</div>
          </div>
        ) : (
          <div
            className="rounded-lg border bg-slate-50 border-slate-200 text-slate-500 px-3 py-2.5 sm:px-4 sm:py-3 col-span-2 md:col-span-1"
            data-testid="student-interview-date"
          >
            <div className="text-[10px] uppercase tracking-widest font-display font-bold opacity-70">
              Interview
            </div>
            <div className="text-sm mt-0.5 italic">No date set</div>
          </div>
        )}

        {/* Interview type — Substantive / Locum */}
        <div
          className={`rounded-lg border px-3 py-2.5 sm:px-4 sm:py-3 ${
            interviewType
              ? "bg-sky-50 border-sky-200 text-sky-900"
              : "bg-slate-50 border-slate-200 text-slate-500"
          }`}
          data-testid="student-interview-type"
        >
          <div className="text-[10px] uppercase tracking-widest font-display font-bold opacity-70">
            Interview type
          </div>
          <div className="font-display font-bold text-base sm:text-lg leading-tight mt-0.5">
            {interviewType || "Not specified"}
          </div>
        </div>

        {/* Speciality */}
        <div
          className={`rounded-lg border px-3 py-2.5 sm:px-4 sm:py-3 ${
            header?.speciality
              ? "bg-violet-50 border-violet-200 text-violet-900"
              : "bg-slate-50 border-slate-200 text-slate-500"
          }`}
          data-testid="student-speciality"
        >
          <div className="text-[10px] uppercase tracking-widest font-display font-bold opacity-70">
            Speciality
          </div>
          <div className="font-display font-bold text-base sm:text-lg leading-tight mt-0.5">
            {header?.speciality || "Not specified"}
          </div>
          {header?.hospital && (
            <div className="text-xs mt-0.5 opacity-80 truncate">{header.hospital}</div>
          )}
        </div>
      </div>
    </div>
  );
}

function PlatformBadges({ result }) {
  const platforms = [
    { key: "monday", label: "Monday" },
    { key: "stripe", label: "Stripe" },
    { key: "circle", label: "Circle" },
    { key: "calendly", label: "Calendly" },
    { key: "tally", label: "Tally" },
  ];
  return (
    <div className="flex flex-wrap gap-1.5">
      {platforms.map((p) => {
        const r = result[p.key];
        // Tally has no `found` flag — derive from history_count
        const found =
          p.key === "tally"
            ? (r?.history_count || 0) > 0
            : !!r?.found;
        const errored = !!r?.error;
        return (
          <span
            key={p.key}
            className={
              "px-2 py-0.5 rounded-full text-[10px] font-medium uppercase tracking-wider " +
              (found
                ? "bg-emerald-100 text-emerald-700"
                : errored
                ? "bg-amber-100 text-amber-700"
                : "bg-slate-100 text-slate-500")
            }
            title={errored ? r.error : found ? "Found" : "Not found"}
            data-testid={`platform-badge-${p.key}`}
          >
            {p.label} {found ? "✓" : errored ? "!" : "—"}
          </span>
        );
      })}
    </div>
  );
}

// Re-export to satisfy ExternalLink import (kept to keep bundler from tree-shaking)
export { ExternalLink };

// ------------------------------------------------------------ StudentNameEditor
// Inline pencil-edit for the student's name on the Lookup header. Saves back
// to the Monday Academy Members board (which is our source of truth) and
// busts the unified-lookup cache so other coaches see the corrected name on
// their next open. Read-only fallback when there's no Monday item id.
function StudentNameEditor({ currentName, mondayItemId, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(currentName);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraft(currentName);
  }, [currentName]);

  if (!mondayItemId) {
    // No Monday record means we can't write back — just render the name.
    return (
      <div
        className="font-display font-bold text-lg sm:text-xl text-[var(--ayci-ink)] truncate"
        data-testid="student-header-name"
      >
        {currentName}
      </div>
    );
  }

  const save = async () => {
    const trimmed = draft.trim();
    if (!trimmed || trimmed === currentName) {
      setEditing(false);
      setDraft(currentName);
      return;
    }
    setSaving(true);
    try {
      await apiClient.patch(`/students/lookup/${mondayItemId}`, { name: trimmed });
      toast.success("Name updated on Monday");
      setEditing(false);
      onSaved?.(trimmed);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Could not save name");
    } finally {
      setSaving(false);
    }
  };

  if (editing) {
    return (
      <div className="flex items-center gap-1.5" data-testid="student-name-editor">
        <Input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") {
              setEditing(false);
              setDraft(currentName);
            }
          }}
          disabled={saving}
          className="h-8 text-base font-display font-bold max-w-sm"
          data-testid="student-name-input"
        />
        <Button
          type="button"
          onClick={save}
          disabled={saving || !draft.trim() || draft.trim() === currentName}
          className="h-8 px-2 bg-emerald-600 hover:bg-emerald-700 text-white"
          data-testid="student-name-save"
          title="Save"
        >
          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => { setEditing(false); setDraft(currentName); }}
          disabled={saving}
          className="h-8 px-2"
          data-testid="student-name-cancel"
          title="Cancel"
        >
          <X className="w-3.5 h-3.5" />
        </Button>
      </div>
    );
  }

  return (
    <div
      className="font-display font-bold text-lg sm:text-xl text-[var(--ayci-ink)] flex items-center gap-1.5 group"
      data-testid="student-header-name"
    >
      <span className="truncate">{currentName}</span>
      <button
        type="button"
        onClick={() => setEditing(true)}
        className="opacity-40 hover:opacity-100 transition-opacity p-1 rounded hover:bg-slate-100"
        title="Edit name (saves to Monday)"
        data-testid="student-name-edit-button"
      >
        <Pencil className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

function isPrivateTier(mondayData) {
  if (!mondayData) return false;
  const tier = mondayData?.columns?.Tier?.text || "";
  const lower = tier.toLowerCase();
  if (!lower) return false;
  // Pure-Academy students don't get private-tier docs
  if (lower === "academy") return false;
  // Anything else is a private / boost / upgrade tier → show the card
  return true;
}
