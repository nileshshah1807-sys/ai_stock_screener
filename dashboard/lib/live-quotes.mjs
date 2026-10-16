/**
 * Intraday quotes beside the model's end-of-day figures.
 *
 * workers/live_quotes.py writes the `live_quotes` table every five minutes
 * during the session. The grid, the stock page and the Market page read it in
 * the browser after the page has rendered, so a page never waits on it: the
 * server sends the last close exactly as before, and the live figure replaces
 * it a moment later where there is one.
 *
 * Display only. Sorting, filters, ranks and ratings all stay on the completed
 * session's close.
 */

/** The worker's cadence. */
export const REFRESH_MS = 5 * 60_000;

/** A run takes ~15 s plus queueing; ask this long after the next one is due. */
const SETTLE_MS = 45_000;

/** Never poll faster than this, whatever the clock says. */
export const MIN_POLL_MS = 30_000;

/**
 * Newer than this, the quotes are live: the worker wrote them on one of its
 * last few runs. Older, the session is over (or the worker stopped), and the
 * page says "as of" rather than "live".
 */
export const LIVE_FOR_MS = 20 * 60_000;

/** While the market is shut, look again this often, in case it opened. */
const CLOSED_POLL_MS = 15 * 60_000;

/**
 * How long to wait before asking again, from when the newest quotes were
 * written. Aligned to the worker's next run rather than a fixed interval, so
 * each viewer asks about once per run however long the page stays open.
 *
 * @param {string | null | undefined} fetchedAt ISO time of the newest quote's run
 * @param {number} now epoch ms
 * @returns {number} ms
 */
export function nextPollDelay(fetchedAt, now) {
  const written = fetchedAt ? Date.parse(fetchedAt) : NaN;
  if (!Number.isFinite(written)) return CLOSED_POLL_MS;
  const age = now - written;
  if (age > LIVE_FOR_MS) return CLOSED_POLL_MS;
  const due = REFRESH_MS + SETTLE_MS - age;
  return Math.min(Math.max(due, MIN_POLL_MS), REFRESH_MS + SETTLE_MS);
}

/**
 * @param {string | null | undefined} fetchedAt
 * @param {number} now epoch ms
 */
export function isLive(fetchedAt, now) {
  const written = fetchedAt ? Date.parse(fetchedAt) : NaN;
  return Number.isFinite(written) && now - written <= LIVE_FOR_MS;
}

/**
 * The quote to show in place of a row's close, or null to keep the close.
 *
 * Only a quote from a later session than the row's bar replaces it: during
 * the session the quote is today's and the bar yesterday's; once the evening
 * run publishes today's close, the bar catches up and the row's own figure
 * stands again. Dates are ISO, so they compare as strings.
 *
 * @template {{ session: string }} Q
 * @param {Q | null | undefined} quote
 * @param {string | null | undefined} barDate
 * @returns {Q | null}
 */
export function liveOverlay(quote, barDate) {
  if (!quote) return null;
  if (!barDate) return quote;
  return quote.session > barDate ? quote : null;
}

/**
 * "11:45" in the exchange's own clock, with the day in front when it is not
 * today there.
 *
 * @param {string | null | undefined} iso
 * @param {string} timeZone
 * @param {string} locale
 * @param {number} now epoch ms
 */
export function quoteTime(iso, timeZone, locale, now) {
  const at = iso ? new Date(iso) : null;
  if (!at || Number.isNaN(at.getTime())) return "";
  /** @param {Date} date */
  const day = (date) => date.toLocaleDateString("en-CA", { timeZone });
  const time = at.toLocaleTimeString(locale, {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  if (day(at) === day(new Date(now))) return time;
  const date = at.toLocaleDateString(locale, { timeZone, day: "numeric", month: "short" });
  return `${date}, ${time}`;
}

/** How long a price that just moved stays tinted, fading out over the end. */
export const TICK_FLASH_MS = 3_000;

/**
 * Which way a price moved between two reads, for the tint behind it: "up",
 * "down", or null when it did not move or there is nothing to compare with.
 * The first quote a tab sees is not a move -- every row would flash on load.
 *
 * @param {number | null | undefined} before
 * @param {number | null | undefined} after
 * @returns {"up" | "down" | null}
 */
export function tickDirection(before, after) {
  if (before === null || before === undefined || after === null || after === undefined) {
    return null;
  }
  if (!Number.isFinite(before) || !Number.isFinite(after) || before === after) return null;
  return after > before ? "up" : "down";
}
