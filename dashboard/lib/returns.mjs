/**
 * The Returns page's arithmetic: what a past ranking's top N would have
 * returned, bought at the next session's close and held to the latest run.
 *
 * Kept free of React and Supabase so `node --test` can exercise it directly.
 * The rules follow the point-in-time backtest (docs/Review/p0.md, p5): a
 * ranking published after a session's close can only be acted on at the next
 * session, so entering at the close that produced it would book a return
 * nobody could have had.
 */

import { decodeDeltas } from "./price-series.mjs";

/** Basket sizes offered. The research studies hold the top 20. */
export const TOP_N_OPTIONS = [10, 20, 50];
export const DEFAULT_TOP_N = 20;

/**
 * Cost per side, in percent of traded value: the flat rate the P5 overlay
 * study declared for brokerage, taxes and slippage together.
 */
export const COST_PER_SIDE_PCT = 0.3;

/**
 * Which model produced each day's ranking.
 *
 * `screener_runs` keeps only the latest runs, so the version is not recorded
 * beside older history. These boundaries were read off `screener_history`
 * itself: no `research_score` before 2026-08-14 (Model 4.x), eligibility-first
 * ordering through 2026-08-20 (Model 5.0), research-score ordering from
 * 2026-08-21 (Model 5.1). The US history starts under 5.1.
 */
export const MODEL_ERAS = {
  NSE: [
    { until: "2026-08-13", label: "Model 4.x" },
    { until: "2026-08-20", label: "Model 5.0" },
    { until: null, label: "Model 5.1" },
  ],
  US: [{ until: null, label: "Model 5.1" }],
};

/**
 * @param {string} market
 * @param {string} date ISO date of the ranking
 * @returns {string | null}
 */
export function modelForDate(market, date) {
  const eras = MODEL_ERAS[market];
  if (!eras || !date) return null;
  for (const era of eras) {
    if (era.until === null || date <= era.until) return era.label;
  }
  return null;
}

/** Minor currency units (paise, cents) per unit, as `workers/price_series.py` stores them. */
const MINOR_UNITS = 100;

/**
 * Expand an encoded `price_series` row into ascending `{ time, close }`.
 *
 * `decodeSeries` in price-series.mjs needs the volume column as well, which
 * this page never reads; selecting it would add a third of the payload for
 * every holding. Returns `[]` on a malformed or misaligned row.
 *
 * @param {{session_deltas: string, closes: string} | null | undefined} row
 * @param {string[]} sessions
 * @returns {{time: string, close: number}[]}
 */
export function decodeCloses(row, sessions) {
  if (!row || !sessions?.length) return [];
  let indices;
  let closes;
  try {
    indices = decodeDeltas(row.session_deltas);
    closes = decodeDeltas(row.closes);
  } catch {
    return [];
  }
  if (indices.length !== closes.length) return [];
  const points = [];
  for (let index = 0; index < indices.length; index += 1) {
    const time = sessions[indices[index]];
    if (time === undefined) continue;
    points.push({ time, close: closes[index] / MINOR_UNITS });
  }
  return points;
}

/**
 * The ranking a requested start date resolves to.
 *
 * A date with no ranking (a weekend, a holiday, a missed run) resolves to the
 * latest ranking on or before it -- the list a reader would actually have had
 * in hand that day. A date before the history begins resolves to its first
 * ranking, and a missing or malformed request to the first as well, so the
 * page opens on the longest record there is.
 *
 * @param {string[]} dates selectable ranking dates, ascending
 * @param {string | null | undefined} requested
 * @returns {string | null}
 */
export function snapRankingDate(dates, requested) {
  if (!dates?.length) return null;
  if (!requested || !/^\d{4}-\d{2}-\d{2}$/.test(requested)) return dates[0];
  let chosen = dates[0];
  for (const date of dates) {
    if (date > requested) break;
    chosen = date;
  }
  return chosen;
}

/**
 * The first session strictly after the ranking date: when its list could first
 * be bought.
 *
 * @param {string[]} sessions ascending
 * @param {string} rankDate
 * @returns {string | null}
 */
export function entrySessionAfter(sessions, rankDate) {
  for (const session of sessions ?? []) {
    if (session > rankDate) return session;
  }
  return null;
}

/**
 * Equal-weight, buy-and-hold basket value from the entry session to `asOf`.
 *
 * Each holding gets 1/N of the money. A holding buys at its close on the entry
 * session, or at its first close after it when it did not trade that day --
 * its slice waits in cash until then rather than being assumed invested. From
 * entry it is marked at its latest close on or before each date, so a thin
 * stock that skips a session keeps its last price instead of dropping to zero.
 * A holding with no close in the window stays in cash throughout and is
 * flagged: dropping it would quietly shrink the basket to the names that kept
 * trading, which is the survivorship the backtest exists to avoid.
 *
 * Costs, when given, are charged once to buy and once to sell, and the curve
 * shows each date's value *as if sold that day*, so the last point is the
 * headline number.
 *
 * @param {{symbol: string, points: {time: string, close: number}[]}[]} holdings
 * @param {{entrySession: string, asOf: string, costPerSidePct?: number}} options
 */
export function basketReturns(holdings, { entrySession, asOf, costPerSidePct = 0 }) {
  const count = holdings.length;
  const retained = (1 - costPerSidePct / 100) ** 2;
  if (!count || !entrySession || !asOf || asOf < entrySession) {
    return { curve: [], stocks: [], grossPct: null, netPct: null };
  }

  const inWindow = holdings.map(({ symbol, points }) => ({
    symbol,
    points: (points ?? []).filter(
      (point) => point.time >= entrySession && point.time <= asOf && point.close > 0,
    ),
  }));

  const times = new Set([entrySession]);
  for (const { points } of inWindow) for (const point of points) times.add(point.time);
  const timeline = [...times].sort();

  // One cursor per holding: the timeline and every series are ascending, so
  // each series is walked once rather than searched per date.
  const cursors = inWindow.map(() => -1);
  const curve = [];
  let lastMultiple = 1;
  for (const time of timeline) {
    let sum = 0;
    inWindow.forEach(({ points }, holding) => {
      while (cursors[holding] + 1 < points.length && points[cursors[holding] + 1].time <= time) {
        cursors[holding] += 1;
      }
      sum += cursors[holding] < 0 ? 1 : points[cursors[holding]].close / points[0].close;
    });
    lastMultiple = sum / count;
    curve.push({ time, value: (lastMultiple * retained - 1) * 100 });
  }

  const stocks = inWindow.map(({ symbol, points }) => {
    const entry = points[0] ?? null;
    const last = points[points.length - 1] ?? null;
    return {
      symbol,
      entry,
      last,
      delayedEntry: Boolean(entry && entry.time > entrySession),
      returnPct: entry && last ? (last.close / entry.close - 1) * 100 : null,
    };
  });

  return {
    curve,
    stocks,
    grossPct: (lastMultiple - 1) * 100,
    netPct: (lastMultiple * retained - 1) * 100,
  };
}

/**
 * An index's return from its first level on or after the entry session.
 *
 * @param {{time: string, value: number}[]} points ascending index levels
 * @param {{entrySession: string, asOf: string}} options
 * @returns {{curve: {time: string, value: number}[], returnPct: number | null, through: string | null}}
 */
export function indexReturns(points, { entrySession, asOf }) {
  const window = (points ?? []).filter(
    (point) => point.time >= entrySession && point.time <= asOf && point.value > 0,
  );
  if (!window.length) return { curve: [], returnPct: null, through: null };
  const base = window[0].value;
  const curve = window.map((point) => ({ time: point.time, value: (point.value / base - 1) * 100 }));
  const last = curve[curve.length - 1];
  return { curve, returnPct: last.value, through: last.time };
}

/**
 * Whether an unadjusted entry/exit pair cannot be trusted as it stands.
 *
 * `screener_history` holds each day's raw close, so a split or bonus inside
 * the window reads as a crash (1:1 bonus, ratio 0.5) and a consolidation as a
 * surge. Anything missing, or outside a band no ordinary month's move reaches
 * for most stocks, is re-read from the adjusted series instead. A genuine
 * large move re-reads to the same answer, so the band only needs to be wide
 * enough to keep the re-read small, not to separate the two cases.
 *
 * @param {number | null | undefined} entry
 * @param {number | null | undefined} last
 */
export function needsAdjustedPrice(entry, last) {
  if (!(entry > 0) || !(last > 0)) return true;
  const ratio = last / entry;
  return ratio < 0.7 || ratio > 1.5;
}

/**
 * Equal-weight return across many entry/exit pairs, in percent.
 *
 * @param {{entry: number, last: number}[]} pairs
 * @returns {number | null}
 */
export function equalWeightReturn(pairs) {
  const usable = (pairs ?? []).filter((pair) => pair.entry > 0 && pair.last > 0);
  if (!usable.length) return null;
  let sum = 0;
  for (const pair of usable) sum += pair.last / pair.entry;
  return (sum / usable.length - 1) * 100;
}

/**
 * Start-date shortcuts, in calendar time back from the latest ranking. `null`
 * months means the first ranking on record.
 */
export const START_PRESETS = [
  { label: "1W", days: 7 },
  { label: "1M", months: 1 },
  { label: "3M", months: 3 },
  { label: "6M", months: 6 },
  { label: "1Y", months: 12 },
  { label: "All", months: null },
];
