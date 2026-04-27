import { useEffect, useState, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { Search, Loader2, RefreshCw, ExternalLink } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import StudentPlatformCard from "@/components/StudentPlatformCard";
import CircleCard from "@/components/student/CircleCard";
import CalendlyCard from "@/components/student/CalendlyCard";
import TallyCard from "@/components/student/TallyCard";
import PrivateDocCard from "@/components/student/PrivateDocCard";
import CoachSummary from "@/components/student/CoachSummary";
import QuickLinks from "@/components/student/QuickLinks";
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
  useEffect(() => {
    const emailParam = searchParams.get("email");
    if (emailParam && emailParam !== query) {
      setSearch(emailParam);
      runLookupForEmail(emailParam);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // Debounced name autocomplete (only when input doesn't look like an email)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const trimmed = search.trim();
    if (trimmed.length < 2 || trimmed.includes("@")) {
      setSuggestions([]);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setSearchingNames(true);
      try {
        const { data } = await apiClient.get(`/students/name-search`, {
          params: { q: trimmed, limit: 8 },
          timeout: 8000,
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

  const runLookupForEmail = async (email) => {
    setLoading(true);
    setResult(null);
    setQuery(email);
    setShowSuggestions(false);
    try {
      const { data } = await apiClient.get(`/students/lookup`, {
        params: { email },
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
      await runLookupForEmail(suggestions[0].email);
    } else {
      toast.info("No matching student found by name");
    }
  };

  const pickSuggestion = (s) => {
    setSearch(s.name || s.email);
    runLookupForEmail(s.email);
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

  // Derive a "student header" from any platform that has a name
  const header = (() => {
    if (!result) return null;
    const name =
      result.circle?.data?.name ||
      result.convertkit?.data?.first_name ||
      result.stripe?.data?.customers?.[0]?.name ||
      result.monday?.data?.name ||
      null;
    const avatar = result.circle?.data?.avatar_url;
    return { name, avatar, email: result.email };
  })();

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="student-lookup-page">
      <div>
        <div className="text-[11px] font-display font-semibold tracking-[0.25em] uppercase text-[var(--ayci-teal)]">
          Unified view
        </div>
        <h1 className="text-4xl font-display font-bold text-[var(--ayci-ink)] mt-1">
          Student Lookup
        </h1>
        <p className="text-[var(--ayci-ink-muted)] text-sm mt-1 max-w-xl">
          Search any student by <strong>email or name</strong> to see a unified profile pulled live from Monday.com,
          Circle, Stripe, ConvertKit and Calendly.
        </p>
      </div>

      <form
        onSubmit={runLookup}
        className="flex flex-wrap items-center gap-3 bg-white border border-[var(--ayci-border)] rounded-lg p-4 shadow-sm"
      >
        <div className="relative flex-1 min-w-[320px]">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[var(--ayci-ink-muted)]" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
            placeholder="Email or name (e.g. anna.swalsh@btinternet.com or Anna Walsh)"
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
          className="bg-[var(--ayci-teal)] hover:bg-[var(--ayci-teal-dark)] text-white h-11 px-5"
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
          className="h-11"
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
          <div className="bg-white border border-[var(--ayci-border)] rounded-lg p-5 shadow-sm flex items-center gap-4">
            {header?.avatar ? (
              <img
                src={header.avatar}
                alt={header.name || "Avatar"}
                className="w-14 h-14 rounded-full object-cover border border-[var(--ayci-border)]"
              />
            ) : (
              <div className="w-14 h-14 rounded-full bg-slate-100 flex items-center justify-center text-slate-500 font-display font-bold">
                {(header?.name || query).slice(0, 2).toUpperCase()}
              </div>
            )}
            <div className="flex-1">
              <div className="font-display font-bold text-xl text-[var(--ayci-ink)]">
                {header?.name || "Unknown student"}
              </div>
              <div className="text-sm text-[var(--ayci-ink-muted)]">{query}</div>
            </div>
            <PlatformBadges result={result} />
          </div>

          {/* Coach summary — at-a-glance tier + calls/videos remaining + last call */}
          <CoachSummary result={result} />

          {/* Quick links — private chat + Google Doc */}
          <QuickLinks result={result} />

          {/* Private-tier Google Doc summary (only for non-pure-Academy students) */}
          {isPrivateTier(result.monday?.data) && (
            <PrivateDocCard
              email={result.email}
              name={header?.name || result.monday?.data?.name || query}
            />
          )}

          {/* Platform cards grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
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
