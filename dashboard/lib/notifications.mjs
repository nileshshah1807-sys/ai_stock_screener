/**
 * What the notification bell and feed say about an event.
 *
 * Kept free of React and of the Supabase client so the wording, the unread
 * rule and the day grouping can be tested directly (see the .test.mjs beside
 * this). A kind this file does not know still renders -- by its name -- so a
 * worker can start writing a new kind before the dashboard learns its wording.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** The exchange's wall clock, for grouping events into its days. */
export const MARKET_TIME_ZONE = { NSE: "Asia/Kolkata", US: "America/New_York" };

export const EVENT_KINDS = [
  { value: "results", label: "Results" },
  { value: "transcript", label: "Transcripts" },
];

/**
 * "Sep 2026" for a quarter-end date. Read from the string, not through Date:
 * `new Date("2026-09-30")` is midnight UTC, which is still the 29th in New
 * York and would label a September quarter correctly only by luck.
 */
export function quarterLabel(value) {
  const match = /^(\d{4})-(\d{2})-\d{2}/.exec(String(value ?? ""));
  if (!match) return null;
  const month = MONTHS[Number(match[2]) - 1];
  return month ? `${month} ${match[1]}` : null;
}

/**
 * Title, one line of detail, and the stock-page tab the event points at.
 *
 * A US result is "published", not "filed": there is no filing index for that
 * market, so what was observed is the vendor's statements gaining the quarter.
 */
export function describeEvent(event) {
  const detail = event?.detail ?? {};
  if (event?.kind === "results") {
    const quarter = quarterLabel(detail.period ?? event.event_key);
    return {
      title: detail.source === "vendor" ? "Results published" : "Results filed",
      summary: quarter ? `Quarter ended ${quarter}` : null,
      tab: "financials",
    };
  }
  if (event?.kind === "transcript") {
    const quarter = quarterLabel(detail.quarter);
    return {
      title: "Earnings call transcript",
      summary: quarter ? `${quarter} quarter` : null,
      tab: null,
    };
  }
  const kind = String(event?.kind ?? "event").replace(/_/g, " ");
  return { title: kind.charAt(0).toUpperCase() + kind.slice(1), summary: null, tab: null };
}

/**
 * New since the viewer last opened the feed. Measured on when the event was
 * recorded, not when it happened: a filing found a day late is still new to
 * the reader. A viewer who has never opened the feed has read nothing.
 */
export function isUnread(event, seenAt) {
  if (!seenAt) return true;
  const detected = Date.parse(event?.detected_at ?? "");
  const seen = Date.parse(seenAt);
  if (Number.isNaN(detected) || Number.isNaN(seen)) return false;
  return detected > seen;
}

/** The badge holds one glyph's width: past nine it says so rather than growing. */
export function badgeText(count) {
  if (!Number.isFinite(count) || count <= 0) return null;
  return count > 9 ? "9+" : String(count);
}

function parts(value, timeZone, options) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return new Intl.DateTimeFormat("en-GB", { timeZone, ...options }).formatToParts(parsed);
}

function part(list, type) {
  return list?.find((item) => item.type === type)?.value ?? "";
}

/** "22:07" on the exchange's clock. Deterministic, so safe to server-render. */
export function eventTime(value, timeZone) {
  const list = parts(value, timeZone, { hour: "2-digit", minute: "2-digit", hour12: false });
  return list ? `${part(list, "hour")}:${part(list, "minute")}` : null;
}

function dayKey(value, timeZone) {
  const list = parts(value, timeZone, { year: "numeric", month: "2-digit", day: "2-digit" });
  return list ? `${part(list, "year")}-${part(list, "month")}-${part(list, "day")}` : null;
}

/**
 * Events grouped by the exchange's calendar day, newest day first, in the
 * order given within a day. `today` is an instant; it only decides which
 * groups are labelled Today and Yesterday.
 *
 * @template {{ occurred_at: string }} T
 * @param {T[]} events
 * @param {string} timeZone
 * @param {Date} [today]
 * @returns {{ key: string, label: string, events: T[] }[]}
 */
export function groupByDay(events, timeZone, today = new Date()) {
  const todayKey = dayKey(today, timeZone);
  const yesterdayKey = dayKey(new Date(new Date(today).getTime() - 86_400_000), timeZone);
  const groups = new Map();
  for (const event of events) {
    const key = dayKey(event.occurred_at, timeZone);
    if (!key) continue;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(event);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => (a < b ? 1 : -1))
    .map(([key, items]) => ({
      key,
      label:
        key === todayKey
          ? "Today"
          : key === yesterdayKey
            ? "Yesterday"
            : `${Number(key.slice(8))} ${MONTHS[Number(key.slice(5, 7)) - 1]} ${key.slice(0, 4)}`,
      events: items,
    }));
}
