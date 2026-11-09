/**
 * The exchange calendar's rows for one day (`market_calendar`, written by the
 * pipeline): a weekday holiday, or a special session such as Muhurat trading.
 * An ordinary day, and any weekend, has no row. Where the table is missing or
 * empty every function here sees `null` and keeps the regular hours.
 *
 * @typedef {{ day: string, kind: "holiday" | "special_session", reason: string,
 *   sessionOpen: string | null, sessionClose: string | null }} MarketDay
 */

/**
 * The date on the exchange's clock, "YYYY-MM-DD".
 *
 * @param {number} now epoch ms
 * @param {string} timeZone
 */
export function localDay(now, timeZone) {
  return new Date(now).toLocaleDateString("en-CA", { timeZone });
}

/**
 * The calendar row that applies at `now`, or null. A page left open past
 * midnight holds yesterday's row, which says nothing about today.
 *
 * @param {MarketDay | null | undefined} marketDay
 * @param {number} now epoch ms
 * @param {string} timeZone
 * @returns {MarketDay | null}
 */
export function dayAt(marketDay, now, timeZone) {
  return marketDay && marketDay.day === localDay(now, timeZone) ? marketDay : null;
}

/**
 * The hours the exchange trades today: a special session's own, none on a
 * holiday, otherwise the regular ones (`day` null).
 *
 * @param {{ sessionOpen: string, sessionClose: string }} market
 * @param {MarketDay | null} day
 * @returns {{ open: string, close: string } | null}
 */
export function tradingHours(market, day) {
  if (day?.kind === "holiday") return null;
  if (day?.kind === "special_session" && day.sessionOpen && day.sessionClose) {
    return { open: day.sessionOpen, close: day.sessionClose };
  }
  return { open: market.sessionOpen, close: market.sessionClose };
}

/**
 * The sentence the notice shows, or null on an ordinary day.
 *
 * @param {MarketDay | null} day
 * @param {string} timezoneLabel "IST"
 */
export function noticeText(day, timezoneLabel) {
  if (!day) return null;
  if (day.kind === "holiday") return `Market closed today: ${day.reason}`;
  const hours = day.sessionOpen && day.sessionClose ? `, ${day.sessionOpen}-${day.sessionClose} ${timezoneLabel}` : "";
  return `Special session: ${day.reason}${hours}`;
}

/** The storage key that remembers a viewer dismissed this day's notice. */
export const noticeDismissKey = (market, day) => `cupel:market-day-notice:${market}:${day}`;

/**
 * A per-instance memo for the day's row. `load` returns `{ row, keep }`: a row
 * or "no row" is kept for `ttlMs`, an error (`keep: false`) is not, so it is
 * retried on the next read.
 *
 * @param {number} ttlMs
 */
export function createDayMemo(ttlMs) {
  /** @type {Map<string, { at: number, row: MarketDay | null }>} */
  const kept = new Map();
  /**
   * @param {string} key
   * @param {number} now epoch ms
   * @param {() => Promise<{ row: MarketDay | null, keep: boolean }>} load
   */
  return async (key, now, load) => {
    const hit = kept.get(key);
    if (hit && now - hit.at < ttlMs) return hit.row;
    const { row, keep } = await load();
    if (keep) kept.set(key, { at: now, row });
    return row;
  };
}
