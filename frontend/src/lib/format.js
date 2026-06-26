export function formatValue(value, format) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const num = Number(value);
  if (format === "currency") {
    return `£${num.toLocaleString("en-GB", { maximumFractionDigits: 0 })}`;
  }
  if (format === "percentage") {
    return `${num.toLocaleString("en-GB", { maximumFractionDigits: 1 })}%`;
  }
  return num.toLocaleString("en-GB", { maximumFractionDigits: 2 });
}

// Monday (week start) in UTC, as YYYY-MM-DD
export function mondayOf(date) {
  const d = new Date(date);
  const day = d.getUTCDay(); // 0 sun .. 6 sat
  const diff = (day === 0 ? -6 : 1) - day; // shift to monday
  d.setUTCDate(d.getUTCDate() + diff);
  return d.toISOString().slice(0, 10);
}

// Returns the last N *completed* week-start Mondays, oldest-first.
// The current (in-progress) week is intentionally excluded - we only review
// fully-finished weeks in the Monday scorecard meeting.
export function lastNWeekStarts(n) {
  const out = [];
  const today = new Date();
  const thisMonday = new Date(mondayOf(today) + "T00:00:00Z");
  // Start from last Monday (thisMonday - 7 days)
  for (let i = n; i >= 1; i--) {
    const d = new Date(thisMonday);
    d.setUTCDate(thisMonday.getUTCDate() - 7 * i);
    out.push(d.toISOString().slice(0, 10));
  }
  return out;
}

export function formatWeekLabel(iso) {
  const d = new Date(iso + "T00:00:00Z");
  const day = d.getUTCDate();
  const month = d.toLocaleString("en-GB", { month: "short", timeZone: "UTC" });
  return `${day} ${month}`;
}

export function formatDateShort(iso) {
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

export function isOnTrack(value, goal, direction = "above") {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  if (goal === null || goal === undefined || Number.isNaN(Number(goal))) return null; // No goal set → no on-track verdict
  if (direction === "below") return Number(value) <= Number(goal);
  return Number(value) >= Number(goal);
}
