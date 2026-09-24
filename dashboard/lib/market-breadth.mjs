/**
 * Reader and chart maths for the Market page.
 *
 * The writer is `workers/market_breadth.py`; the two must agree. A row carries
 * its own sessions (delta-encoded days since 1970-01-01) and a `series` map of
 * delta-encoded integer arrays: counts per breadth metric with their own
 * denominators, or `c` -- an index level in hundredths.
 *
 * Kept free of React so `node --test` can exercise it directly.
 */

import { decodeDeltas } from "./price-series.mjs";

const DAY_MS = 86_400_000;

/** Undo delta encoding on an already-parsed array. */
function undelta(values) {
  if (!Array.isArray(values)) return [];
  const out = new Array(values.length);
  for (let index = 0; index < values.length; index += 1) {
    out[index] = index === 0 ? values[0] : out[index - 1] + values[index];
  }
  return out;
}

/**
 * Expand a published row. Returns null on a malformed row rather than
 * throwing, so one broken group cannot take the whole page down.
 *
 * @param {{sessions: string, series: string} | null | undefined} row
 * @returns {{dates: string[], series: Record<string, number[]>} | null}
 */
export function decodeRow(row) {
  if (!row?.sessions || !row?.series) return null;
  try {
    const days = decodeDeltas(row.sessions);
    const dates = days.map((day) => new Date(day * DAY_MS).toISOString().slice(0, 10));
    const raw = JSON.parse(row.series);
    /** @type {Record<string, number[]>} */
    const series = {};
    for (const [key, values] of Object.entries(raw)) {
      const decoded = undelta(values);
      if (decoded.length !== dates.length) return null;
      series[key] = decoded;
    }
    return { dates, series };
  } catch {
    return null;
  }
}

/**
 * One chart's points: `{ time, value, count, total }`.
 *
 * `share` turns a count into a percentage of its own denominator; a session
 * where the denominator is zero is dropped, not drawn as 0%, because nothing
 * was measured that day.
 *
 * @param {{dates: string[], series: Record<string, number[]>}} decoded
 * @param {string} key numerator key, e.g. "e50"
 * @param {string} totalKey denominator key, e.g. "e50d"
 * @param {"share" | "count"} unit
 */
export function metricPoints(decoded, key, totalKey, unit) {
  const counts = decoded?.series?.[key];
  const totals = decoded?.series?.[totalKey];
  if (!counts || !totals) return [];
  const out = [];
  for (let index = 0; index < decoded.dates.length; index += 1) {
    const total = totals[index];
    if (!(total > 0)) continue;
    const count = counts[index];
    out.push({
      time: decoded.dates[index],
      value: unit === "share" ? (count / total) * 100 : count,
      count,
      total,
    });
  }
  return out;
}

/** An index level, from hundredths. */
export function indexPoints(decoded) {
  const closes = decoded?.series?.c;
  if (!closes) return [];
  return decoded.dates.map((time, index) => ({ time, value: closes[index] / 100 }));
}

/**
 * Metrics with a published list of today's stocks (`market_breadth_members`),
 * i.e. the valid values of the page's `?list=` parameter.
 */
export const LIST_METRICS = ["e20", "e50", "e100", "e200", "s2", "bb", "rs", "hi", "lo"];

/**
 * Time range buttons. Each is calendar days or calendar months (never both);
 * `null` months means everything. Days come before months so a week reads as
 * a proper trend line -- a single session has no shape to show.
 */
export const RANGES = [
  { label: "1W", days: 7 },
  { label: "1M", months: 1 },
  { label: "3M", months: 3 },
  { label: "6M", months: 6 },
  { label: "1Y", months: 12 },
  { label: "3Y", months: 36 },
  { label: "5Y", months: 60 },
  { label: "Max", months: null },
];

/**
 * First date of a range ending on `last`, as `YYYY-MM-DD`.
 *
 * Calendar days or months rather than a session count, so every chart on the
 * page -- NSE sessions, an index on Yahoo's calendar -- shares one left edge
 * and the synced crosshair lines up across them.
 *
 * @param {string} last
 * @param {number | null} months
 * @param {number | null} [days]
 */
export function rangeStart(last, months, days) {
  if (!last) return null;
  if (days) {
    const date = new Date(`${last}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() - days);
    return date.toISOString().slice(0, 10);
  }
  if (!months) return null;
  const date = new Date(`${last}T00:00:00Z`);
  const day = date.getUTCDate();
  date.setUTCDate(1);
  date.setUTCMonth(date.getUTCMonth() - months);
  const lastDay = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate();
  date.setUTCDate(Math.min(day, lastDay));
  return date.toISOString().slice(0, 10);
}

/**
 * Points on or after `from`. The first point is kept even if it falls just
 * before `from`, so a range never starts with an empty stretch.
 *
 * @template {{time: string}} T
 * @param {T[]} points
 * @param {string | null} from
 * @returns {T[]}
 */
export function sliceFrom(points, from) {
  if (!from || !points.length) return points;
  const start = firstIndexOnOrAfter(points, from);
  return points.slice(Math.max(0, start === points.length ? points.length - 1 : start));
}

/**
 * Index of the first point dated on or after `time` (binary search).
 *
 * @param {{time: string}[]} points
 * @param {string} time
 */
export function firstIndexOnOrAfter(points, time) {
  let low = 0;
  let high = points.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (points[mid].time < time) low = mid + 1;
    else high = mid;
  }
  return low;
}

/**
 * The point to show for a hovered date: the latest on or before it.
 *
 * On-or-before rather than nearest, because a date the series did not trade
 * should read as "the last known value", not borrow tomorrow's.
 *
 * @template {{time: string}} T
 * @param {T[]} points
 * @param {string} time
 * @returns {T | null}
 */
export function pointAt(points, time) {
  if (!points.length) return null;
  const index = firstIndexOnOrAfter(points, time);
  if (index < points.length && points[index].time === time) return points[index];
  return index > 0 ? points[index - 1] : null;
}

/**
 * A "nice" y-axis: padded bounds on round steps, about `count` ticks.
 *
 * `clamp` pins the domain inside hard limits -- a share can never leave 0-100.
 *
 * @param {number} min
 * @param {number} max
 * @param {{count?: number, clamp?: [number, number]}} [options]
 * @returns {{min: number, max: number, ticks: number[]}}
 */
export function niceScale(min, max, { count = 4, clamp } = {}) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { min: 0, max: 1, ticks: [0, 1] };
  if (min === max) {
    const pad = Math.abs(min) * 0.05 || 1;
    min -= pad;
    max += pad;
  }
  const rough = (max - min) / count;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rough) ?? 10 * magnitude;
  let low = Math.floor(min / step) * step;
  let high = Math.ceil(max / step) * step;
  if (clamp) {
    low = Math.max(clamp[0], low);
    high = Math.min(clamp[1], high);
  }
  const ticks = [];
  for (let tick = low; tick <= high + step / 1e6; tick += step) {
    ticks.push(Number(tick.toFixed(10)));
  }
  return { min: low, max: high, ticks };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * X-axis ticks for a date span: weeks under ~7 weeks, then months on the
 * smallest step that keeps the axis to about `max` labels, then years.
 *
 * A month tick is labelled with its year at January (or when it is the first
 * tick), so "Nov Dec 2026 Feb" never happens.
 *
 * @param {string} from
 * @param {string} to
 * @param {number} [max]
 * @returns {{time: string, label: string}[]}
 */
export function timeTicks(from, to, max = 6) {
  if (!from || !to || from >= to) return [];
  const start = new Date(`${from}T00:00:00Z`);
  const end = new Date(`${to}T00:00:00Z`);
  const days = (end.getTime() - start.getTime()) / DAY_MS;
  const ticks = [];

  if (days <= 50) {
    const step = days <= 35 ? 7 : 14;
    const cursor = new Date(start);
    // Mondays read as the start of a trading week.
    cursor.setUTCDate(cursor.getUTCDate() + ((8 - cursor.getUTCDay()) % 7 || 7));
    while (cursor <= end) {
      ticks.push({
        time: cursor.toISOString().slice(0, 10),
        label: `${cursor.getUTCDate()} ${MONTHS[cursor.getUTCMonth()]}`,
      });
      cursor.setUTCDate(cursor.getUTCDate() + step);
    }
    return ticks;
  }

  const months = days / 30.44;
  const step = [1, 2, 3, 6, 12, 24].find((s) => months / s <= max) ?? 24;
  const cursor = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 1));
  while (cursor <= end) {
    const month = cursor.getUTCMonth();
    const aligned = step >= 12 ? month === 0 && cursor.getUTCFullYear() % (step / 12) === 0 : month % step === 0;
    if (aligned) {
      const year = cursor.getUTCFullYear();
      const label =
        step >= 12 ? String(year) : month === 0 || ticks.length === 0 ? `${MONTHS[month]} ${year}` : MONTHS[month];
      ticks.push({ time: cursor.toISOString().slice(0, 10), label });
    }
    cursor.setUTCMonth(cursor.getUTCMonth() + 1);
  }
  return ticks;
}

/** Milliseconds since epoch for a `YYYY-MM-DD`, for the x scale. */
export function timeValue(time) {
  return Date.parse(`${time}T00:00:00Z`);
}
