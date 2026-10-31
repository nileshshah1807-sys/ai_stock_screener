/**
 * Upcoming events: board meetings that will approve results, and calls that
 * will be held. One row per (market, kind, symbol, event_date):
 * `{ kind: "results" | "call", symbol, company, event_date: "YYYY-MM-DD",
 * event_time: ISO with the IST offset | null }`. A results row has a date and
 * never a time; a call has a time when the notice stated one.
 *
 * Pure functions, shared by the server pages and the sheet.
 */

/** Most days of events one list reads: the notices run about a week ahead, up to 40 days. */
export const HORIZON_DAYS = 45;

const DAY_MS = 86_400_000;

function addDays(iso, days) {
  return new Date(Date.parse(`${iso}T00:00:00Z`) + days * DAY_MS).toISOString().slice(0, 10);
}

/** Rows from `today` on, soonest first; a call with no stated time follows the timed ones of its day. */
export function sortUpcoming(rows, today) {
  return (rows ?? [])
    .filter((row) => row.event_date >= today)
    .sort(
      (a, b) =>
        a.event_date.localeCompare(b.event_date) ||
        (a.event_time ? 0 : 1) - (b.event_time ? 0 : 1) ||
        (a.event_time ?? "").localeCompare(b.event_time ?? "") ||
        a.symbol.localeCompare(b.symbol),
    );
}

/**
 * Rows grouped by day, with each run of days that has none folded into one
 * `{ gap: true, from, to, days }` so a quiet weekend is a line, not two empty
 * sections. Today is always a day of its own, empty or not.
 */
export function groupUpcoming(rows, today) {
  const sorted = sortUpcoming(rows, today);
  const days = new Map();
  for (const row of sorted) {
    if (!days.has(row.event_date)) days.set(row.event_date, []);
    days.get(row.event_date).push(row);
  }
  const last = sorted.length ? sorted[sorted.length - 1].event_date : today;
  const groups = [];
  let gap = null;
  for (let date = today; date <= last; date = addDays(date, 1)) {
    const entries = days.get(date) ?? [];
    if (entries.length || date === today) {
      gap = null;
      groups.push({ date, isToday: date === today, rows: entries });
    } else if (gap) {
      gap.to = date;
      gap.days += 1;
    } else {
      gap = { gap: true, from: date, to: date, days: 1 };
      groups.push(gap);
    }
  }
  return groups;
}

/**
 * Rows whose symbol or company holds `search`, and (when `symbols` is given) that are on the list.
 * @param {{ symbol: string, company?: string | null }[]} rows
 * @param {{ search?: string, symbols?: string[] | null }} [options]
 */
export function filterUpcoming(rows, { search = "", symbols = null } = {}) {
  const term = search.trim().toLowerCase();
  const allowed = symbols ? new Set(symbols) : null;
  return (rows ?? []).filter(
    (row) =>
      (!allowed || allowed.has(row.symbol)) &&
      (!term || row.symbol.toLowerCase().includes(term) || (row.company ?? "").toLowerCase().includes(term)),
  );
}

/** "12:30" in India's clock, or null when the notice named no time. */
export function callTime(eventTime, timeZone = "Asia/Kolkata") {
  if (!eventTime) return null;
  const parsed = new Date(eventTime);
  if (Number.isNaN(parsed.getTime())) return null;
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone,
  }).format(parsed);
}

/** The count and the next call for the tiles: results from today on, and the first call not yet over. */
export function upcomingSummary(rows, today, now = new Date()) {
  const sorted = sortUpcoming(rows, today);
  const next = sorted.find((row) => !row.event_time || new Date(row.event_time) >= now) ?? null;
  return { count: sorted.length, next };
}

/** The date of this company's coming results, or null. */
export function upcomingResultDate(rows, symbol, today) {
  const found = sortUpcoming(rows, today).find((row) => row.symbol === symbol);
  return found ? found.event_date : null;
}
