/**
 * Today's line of a headline index on the home page's tiles: the five-minute
 * levels the live-quotes worker publishes (`live/{MARKET}/intraday.json`,
 * workers/live_quotes.py publish_intraday), drawn across the whole session so
 * a line at noon fills half the tile, against the previous close the tile's
 * own 1D implies (`dayBase`).
 *
 * @typedef {[number, number]} Point  [epoch seconds, level]
 * @typedef {{ name: string, points: Point[] }} IntradayRow
 * @typedef {{ session?: string, written_at?: string, rows?: IntradayRow[] }} IntradayObject
 */

/** "2026-11-26": the calendar day at `now` in the exchange's clock. */
export function marketDate(now, timeZone) {
  return new Date(now).toLocaleDateString("en-CA", { timeZone });
}

/** Minutes between two "HH:MM" clock times. */
function minutes(open, close) {
  const [oh, om] = open.split(":").map(Number);
  const [ch, cm] = close.split(":").map(Number);
  return ch * 60 + cm - (oh * 60 + om);
}

/**
 * One index's line, only when the object is from `today`: before the next
 * session opens, the tile goes back to the month rather than show yesterday
 * as if it were today.
 *
 * @param {IntradayObject | null | undefined} object
 * @param {string} name
 * @param {string} today
 * @returns {IntradayRow | null}
 */
export function intradayFor(object, name, today) {
  if (!object || object.session !== today) return null;
  const row = object.rows?.find((entry) => entry.name === name);
  return row && row.points?.length ? row : null;
}

/**
 * The previous close behind a printed level and its day's change, so the
 * line's baseline and colour always agree with the 1D beside it. Yahoo's own
 * previous close is two sessions old after a holiday.
 *
 * @param {number} level
 * @param {number | null | undefined} dayPct
 * @returns {number | null}
 */
export function dayBase(level, dayPct) {
  const base = level / (1 + Number(dayPct) / 100);
  return dayPct != null && Number.isFinite(base) && base > 0 ? base : null;
}

/**
 * The line with the live level on the end, when the quote is newer than its
 * last bar, so the line finishes on the number the tile prints.
 *
 * @param {Point[]} points
 * @param {number | null | undefined} price
 * @param {string | null | undefined} tradedAt ISO time of that price
 * @returns {Point[]}
 */
export function withLivePoint(points, price, tradedAt) {
  const at = tradedAt ? Math.floor(Date.parse(tradedAt) / 1000) : NaN;
  const last = points.at(-1);
  if (!last || !Number.isFinite(at) || !(Number(price) > 0) || at <= last[0]) return points;
  return [...points, [at, Number(price)]];
}

/**
 * The SVG geometry of a line: x across the session from its first bar, y
 * between the day's extremes and the previous close (so the close's dashed
 * line is always inside the box).
 *
 * @param {Point[]} points
 * @param {{ base: number | null, sessionOpen: string, sessionClose: string, width: number, height: number, pad?: number }} box
 * @returns {{ line: string, last: [number, number], baseY: number | null, rising: boolean } | null}
 */
export function intradayGeometry(points, { base, sessionOpen, sessionClose, width, height, pad = 2 }) {
  if (!points.length) return null;
  const start = points[0][0];
  const span = Math.max(minutes(sessionOpen, sessionClose) * 60, points.at(-1)[0] - start, 1);
  const levels = points.map((point) => point[1]);
  const withBase = base ? [...levels, base] : levels;
  const low = Math.min(...withBase);
  const high = Math.max(...withBase);
  const range = high - low || 1;
  const x = (t) => ((t - start) / span) * width;
  const y = (v) => pad + (1 - (v - low) / range) * (height - pad * 2);
  const coords = points.map(([t, v]) => [Number(x(t).toFixed(1)), Number(y(v).toFixed(1))]);
  const last = coords.at(-1);
  return {
    line: coords.map(([px, py]) => `${px},${py}`).join(" "),
    last,
    baseY: base ? Number(y(base).toFixed(1)) : null,
    rising: levels.at(-1) >= (base ?? levels[0]),
  };
}
