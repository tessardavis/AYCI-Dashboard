// Client-side port of backend calendly_webhook.summarize_private_calls, so the
// Students DB modal can compute a private-tier allowance view from the raw row
// (tier + private_calls array + private_call_allowance override) without an
// extra round-trip. Keep in sync with the Python version.

const PRIVATE_ALLOWANCE = {
  "Private Plus": { coach_30: 1 },
  VIP: { tessa_30: 2, coach_30: 2, mock_60: 1 },
};
const PRIVATE_KIND_LABELS = {
  coach_30: "30-min coach call",
  tessa_30: "30-min call with Tessa",
  mock_60: "60-min mock interview",
};
const KIND_ORDER = ["tessa_30", "coach_30", "mock_60"];

function normalizeTier(tier) {
  const t = (tier || "").toLowerCase();
  if (t.includes("vip")) return "VIP";
  if (t.includes("private plus")) return "Private Plus";
  return null;
}

export function summarizePrivateCalls(tier, calls, extra) {
  const norm = normalizeTier(tier);
  const base = PRIVATE_ALLOWANCE[norm] || {};
  const ex = {};
  for (const [k, v] of Object.entries(extra || {})) if (v) ex[k] = v;
  calls = calls || [];

  const kindSet = new Set([
    ...Object.keys(base),
    ...Object.keys(ex),
    ...calls.map((c) => c.kind).filter(Boolean),
  ]);
  const order = {};
  KIND_ORDER.forEach((k, i) => (order[k] = i));
  const kinds = [...kindSet].sort(
    (a, b) => ((order[a] ?? 99) - (order[b] ?? 99)) || (a < b ? -1 : 1)
  );

  const by_kind = {};
  for (const kind of kinds) {
    const allow = (base[kind] || 0) + (ex[kind] || 0);
    const entries = calls.filter((c) => c.kind === kind);
    const active = entries.filter((c) => !["Cancelled", "No-show"].includes(c.status));
    by_kind[kind] = {
      label: PRIVATE_KIND_LABELS[kind] || kind,
      allowance: allow,
      extra: ex[kind] || 0,
      booked: active.length,
      remaining: Math.max(0, allow - active.length),
      calls: entries.slice().sort((a, b) => (a.date || "").localeCompare(b.date || "")),
    };
  }
  const totalAllow = Object.values(by_kind).reduce((s, v) => s + v.allowance, 0);
  const totalBooked = Object.values(by_kind).reduce((s, v) => s + v.booked, 0);
  return {
    tier: norm,
    eligible: Object.keys(by_kind).length > 0,
    total_allowance: totalAllow,
    total_booked: totalBooked,
    total_remaining: Math.max(0, totalAllow - totalBooked),
    by_kind,
  };
}
