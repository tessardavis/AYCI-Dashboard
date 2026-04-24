import { useState } from "react";
import { Search, Loader2, RefreshCw, ExternalLink } from "lucide-react";
import { toast } from "sonner";

import { apiClient, formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import StudentPlatformCard from "@/components/StudentPlatformCard";
import MondayCard from "@/components/student/MondayCard";
import StripeCard from "@/components/student/StripeCard";
import ConvertKitCard from "@/components/student/ConvertKitCard";
import CircleCard from "@/components/student/CircleCard";
import CalendlyCard from "@/components/student/CalendlyCard";
import PrivateDocCard from "@/components/student/PrivateDocCard";

export default function StudentLookup() {
  const [email, setEmail] = useState("");
  const [query, setQuery] = useState(""); // the email we searched for (persists across typing)
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [refreshingCache, setRefreshingCache] = useState(false);

  const runLookup = async (e) => {
    e?.preventDefault();
    const trimmed = email.trim().toLowerCase();
    if (!trimmed || !trimmed.includes("@")) {
      toast.error("Please enter a valid email address");
      return;
    }
    setLoading(true);
    setResult(null);
    setQuery(trimmed);
    try {
      const { data } = await apiClient.get(`/students/lookup`, {
        params: { email: trimmed },
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
    <div className="p-8 space-y-6" data-testid="student-lookup-page">
      <div>
        <div className="text-[11px] font-display font-semibold tracking-[0.25em] uppercase text-[var(--ayci-teal)]">
          Unified view
        </div>
        <h1 className="text-4xl font-display font-bold text-[var(--ayci-ink)] mt-1">
          Student Lookup
        </h1>
        <p className="text-[var(--ayci-ink-muted)] text-sm mt-1 max-w-xl">
          Search any student by email to see a unified profile pulled live from Monday.com,
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
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="student@example.com"
            type="email"
            className="pl-9 h-11"
            data-testid="student-lookup-email-input"
            autoFocus
          />
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
              title="Monday.com — Academy Members"
              platform="monday"
              state={result.monday}
              accent="#ff3d57"
            >
              <MondayCard data={result.monday?.data} />
            </StudentPlatformCard>

            <StudentPlatformCard
              title="Stripe — Payments"
              platform="stripe"
              state={result.stripe}
              accent="#635bff"
            >
              <StripeCard data={result.stripe?.data} />
            </StudentPlatformCard>

            <StudentPlatformCard
              title="ConvertKit — Email"
              platform="convertkit"
              state={result.convertkit}
              accent="#fb6970"
            >
              <ConvertKitCard data={result.convertkit?.data} />
            </StudentPlatformCard>

            <StudentPlatformCard
              title="Circle — Community"
              platform="circle"
              state={result.circle}
              accent="#7c3aed"
            >
              <CircleCard data={result.circle?.data} />
            </StudentPlatformCard>

            <StudentPlatformCard
              title="Calendly — Past calls"
              platform="calendly"
              state={result.calendly}
              accent="#006bff"
            >
              <CalendlyCard data={result.calendly?.data} />
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
    { key: "convertkit", label: "ConvertKit" },
    { key: "circle", label: "Circle" },
    { key: "calendly", label: "Calendly" },
  ];
  return (
    <div className="flex flex-wrap gap-1.5">
      {platforms.map((p) => {
        const r = result[p.key];
        const found = r?.found;
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
