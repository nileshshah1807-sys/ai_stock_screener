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
 * Rebalance frequencies offered, as stops on a slider. Fixed stops rather than
 * a free number of days: a free slider invites trying periods until one looks
 * good, which is choosing a result after seeing it. Monthly and quarterly are
 * the horizons the research studies tested; the weekly stops show what faster
 * turnover costs.
 */
export const REBALANCE_OPTIONS = [
  { value: "never", label: "Never" },
  { value: "1w", label: "1W", days: 7 },
  { value: "2w", label: "2W", days: 14 },
  { value: "1m", label: "1M", months: 1 },
  { value: "3m", label: "3M", months: 3 },
];

/**
 * @param {string | null | undefined} value
 */
export function rebalanceOption(value) {
  return REBALANCE_OPTIONS.find((option) => option.value === value) ?? REBALANCE_OPTIONS[0];
}

/**
 * `date` moved forward by an option's period, as `YYYY-MM-DD`. A month step
 * clamps to the month's last day, so 31 Jan + 1M is 28/29 Feb, not 3 Mar.
 *
 * @param {string} date
 * @param {{days?: number, months?: number}} option
 */
export function addPeriod(date, option) {
  const next = new Date(`${date}T00:00:00Z`);
  if (option.days) {
    next.setUTCDate(next.getUTCDate() + option.days);
    return next.toISOString().slice(0, 10);
  }
  const day = next.getUTCDate();
  next.setUTCDate(1);
  next.setUTCMonth(next.getUTCMonth() + (option.months ?? 0));
  const lastDay = new Date(Date.UTC(next.getUTCFullYear(), next.getUTCMonth() + 1, 0)).getUTCDate();
  next.setUTCDate(Math.min(day, lastDay));
  return next.toISOString().slice(0, 10);
}

/**
 * The rankings a rebalanced basket is rebuilt from: the start, then the first
 * published ranking on or after each period boundary. The next boundary is
 * measured from the ranking actually used, so a missed run shifts the rest of
 * the schedule instead of bunching two rebalances together.
 *
 * @param {string[]} rankingDates ascending
 * @param {string} start the chosen ranking date
 * @param {{days?: number, months?: number}} option
 * @returns {string[]}
 */
export function rebalanceDates(rankingDates, start, option) {
  const dates = [start];
  if (!option?.days && !option?.months) return dates;
  let next = addPeriod(start, option);
  for (const date of rankingDates ?? []) {
    if (date <= start || date < next) continue;
    dates.push(date);
    next = addPeriod(date, option);
  }
  return dates;
}

/**
 * One pass of the portfolio simulation at a single cost rate.
 *
 * @param {{entrySession: string, symbols: string[]}[]} rounds
 * @param {Map<string, {time: string, close: number}[]>} series
 * @param {string} asOf
 * @param {number} cost fraction of traded value, per side
 */
function simulate(rounds, series, asOf, cost) {
  const start = rounds[0].entrySession;
  const times = new Set(rounds.map((round) => round.entrySession));
  for (const points of series.values()) {
    for (const point of points) if (point.time >= start && point.time <= asOf) times.add(point.time);
  }
  const timeline = [...times].filter((time) => time <= asOf).sort();
  const roundAt = new Map(rounds.map((round) => [round.entrySession, round]));

  // One cursor per series: the timeline and every series are ascending, so
  // each series is walked once rather than searched per date.
  const cursors = new Map([...series.keys()].map((symbol) => [symbol, -1]));
  const lastClose = (symbol) => {
    const index = cursors.get(symbol) ?? -1;
    return index < 0 ? null : series.get(symbol)[index];
  };
  const valueOf = (symbol, position) =>
    position.pending !== null ? position.pending : position.units * lastClose(symbol).close;

  /** @type {Map<string, {units: number | null, pending: number | null, since: string, entry: {time: string, close: number} | null}>} */
  let positions = new Map();
  let cash = 1;
  const curve = [];
  const trades = [];
  let value = 1;

  for (const time of timeline) {
    for (const [symbol, points] of series) {
      let index = cursors.get(symbol);
      while (index + 1 < points.length && points[index + 1].time <= time) index += 1;
      cursors.set(symbol, index);
    }

    // A name that had no close when it was bought is filled at its first
    // close after; until then its slice waits in cash.
    for (const [symbol, position] of positions) {
      const close = lastClose(symbol);
      if (position.pending !== null && close && close.time === time) {
        position.units = position.pending / close.close;
        position.pending = null;
        position.entry = close;
      }
    }

    const round = roundAt.get(time);
    if (round && round.symbols.length) {
      let before = cash;
      const current = new Map();
      for (const [symbol, position] of positions) {
        const held = valueOf(symbol, position);
        current.set(symbol, held);
        before += held;
      }
      const targets = new Set(round.symbols);
      const share = before / targets.size;
      // Cash is not a position: moving into or out of it is the trade.
      let traded = 0;
      for (const symbol of new Set([...targets, ...current.keys()])) {
        traded += Math.abs((targets.has(symbol) ? share : 0) - (current.get(symbol) ?? 0));
      }
      const charged = traded * cost;
      const each = (before - charged) / targets.size;

      const next = new Map();
      for (const symbol of round.symbols) {
        const held = positions.get(symbol);
        const close = lastClose(symbol);
        if (held && held.pending === null) {
          next.set(symbol, { ...held, units: each / close.close });
        } else if (held) {
          next.set(symbol, { ...held, pending: each });
        } else if (close && close.time === time) {
          next.set(symbol, { units: each / close.close, pending: null, since: time, entry: close });
        } else {
          next.set(symbol, { units: null, pending: each, since: time, entry: null });
        }
      }
      trades.push({
        entrySession: time,
        bought: round.symbols.filter((symbol) => !positions.has(symbol)),
        sold: [...positions.keys()].filter((symbol) => !targets.has(symbol)),
        costPct: before > 0 ? (charged / before) * 100 : 0,
      });
      positions = next;
      cash = 0;
    }

    value = cash;
    for (const [symbol, position] of positions) value += valueOf(symbol, position);
    // As if sold that day, so the last point is the headline number.
    curve.push({ time, value: (value * (1 - cost) - 1) * 100 });
  }

  return { curve, trades, positions, value, lastClose };
}

/**
 * Equal-weight basket value from the first round's entry session to `asOf`,
 * rebuilt at each later round.
 *
 * Each round buys the given names at their close on its entry session (the
 * session after the ranking), selling what dropped out and resetting every
 * holding to equal weight. A name that did not trade that session is bought at
 * its first close after it; its slice waits in cash rather than being assumed
 * invested. Holdings are marked at their latest close, so a thin stock that
 * skips a session keeps its last price instead of dropping to zero, and a name
 * that stops trading is carried, never dropped -- dropping it would quietly
 * shrink the basket to the names that kept trading, which is the survivorship
 * the backtest exists to avoid.
 *
 * With one round this is buy-and-hold. Costs, when given, are charged on the
 * value actually traded at each round and once more on a final sale, so a
 * rebalance that keeps most names costs only its turnover.
 *
 * @param {{entrySession: string, symbols: string[]}[]} rounds ascending
 * @param {Map<string, {time: string, close: number}[]>} closes ascending points per symbol
 * @param {{asOf: string, costPerSidePct?: number}} options
 */
export function portfolioReturns(rounds, closes, { asOf, costPerSidePct = 0 }) {
  const usable = (rounds ?? []).filter((round) => round.entrySession && round.entrySession <= asOf);
  if (!usable.length || !usable[0].symbols.length) {
    return { curve: [], grossCurve: [], trades: [], stocks: [], grossPct: null, netPct: null };
  }
  const series = new Map();
  for (const round of usable) {
    for (const symbol of round.symbols) {
      if (series.has(symbol)) continue;
      series.set(
        symbol,
        (closes.get(symbol) ?? []).filter((point) => point.close > 0 && point.time <= asOf),
      );
    }
  }

  const gross = simulate(usable, series, asOf, 0);
  const net = simulate(usable, series, asOf, costPerSidePct / 100);

  const holdings = usable[usable.length - 1].symbols;
  const stocks = holdings.map((symbol) => {
    const position = net.positions.get(symbol);
    const entry = position?.entry ?? null;
    const last = net.lastClose(symbol);
    return {
      symbol,
      heldSince: position?.since ?? null,
      entry,
      last: entry ? last : null,
      delayedEntry: Boolean(entry && position && entry.time > position.since),
      returnPct: entry && last ? (last.close / entry.close - 1) * 100 : null,
    };
  });

  return {
    curve: net.curve,
    // Both, so a reader can switch costs on and off without another request.
    grossCurve: gross.curve,
    trades: net.trades,
    stocks,
    grossPct: (gross.value - 1) * 100,
    netPct: net.curve.length ? net.curve[net.curve.length - 1].value : null,
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
