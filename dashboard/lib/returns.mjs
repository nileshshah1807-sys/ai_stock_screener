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

/**
 * What the basket picks from: the whole ranking, or one filtered list of it,
 * taking the top N of that list. Backtest rankings store each list's own rank
 * (`column`); published ones are filtered at read time by the same rule, which
 * matches `PICKS` in tools/backfill_returns_history.py.
 *
 * P0 found gating by rating cost 5-16 points a year as a selection rule, and
 * P4 found a fresh-Stage-2 tilt negative in both halves; these picks exist to
 * let a reader see that, not because they are expected to do better.
 */
export const FRESH_STAGE2_DAYS = 30;
export const PICK_OPTIONS = [
  { value: "all", label: "All", title: "The whole ranking" },
  {
    value: "buy",
    label: "Buy+",
    title: "Only stocks rated BUY or STRONG BUY",
    column: "rank_buy",
    ratings: ["BUY", "STRONG BUY"],
    hold: "buy_plus",
    phrase: "BUY-or-better",
  },
  {
    value: "strong_buy",
    label: "Strong Buy",
    title: "Only stocks rated STRONG BUY",
    column: "rank_strong_buy",
    ratings: ["STRONG BUY"],
    hold: "buy_plus",
    phrase: "STRONG BUY",
  },
  {
    value: "stage2",
    label: "Stage 2",
    title: "Only stocks in Stage 2",
    column: "rank_stage2",
    stage: "Stage 2",
    hold: "advancing",
    phrase: "Stage 2",
  },
  {
    value: "fresh_stage2",
    label: "Fresh S2",
    title: `Stage 2, with the advance begun within ${FRESH_STAGE2_DAYS} days`,
    column: "rank_fresh_stage2",
    stage: "Stage 2",
    maxAdvanceAge: FRESH_STAGE2_DAYS,
    hold: "advancing",
    phrase: "fresh Stage 2",
  },
];

/**
 * @param {string | null | undefined} value
 */
export function pickOption(value) {
  return PICK_OPTIONS.find((option) => option.value === value) ?? PICK_OPTIONS[0];
}

/** Stages a stock may stay held in under a stage pick: the advance, pullbacks included. */
export const ADVANCING_STAGES = ["Stage 2", "S2 Candidate"];

/**
 * Which stocks the basket holds at each round, given buy lists and hold rules.
 *
 * A pick says what to *buy*; its hold rule says what may be *kept*. So each
 * round keeps every holding that still passes the hold rule (a stage pick
 * keeps a stock while it is advancing and sells it on a break into Stage 3 or
 * 4; a rating pick keeps it while it is rated BUY or better), then fills the
 * free slots from the round's buy list in rank order. Without that split, a
 * "fresh Stage 2" basket sold every name the week it stopped being fresh.
 *
 * `keep` is the set of symbols allowed to stay that round; null means no hold
 * rule, and the round is simply its buy list's top N -- which is also what the
 * whole-ranking pick does. Holdings depend only on these lists, never on
 * prices, so the baskets are settled before any price is read.
 *
 * @param {{candidates: string[], keep: Set<string> | null}[]} rounds oldest first
 * @param {number} topN
 * @returns {string[][]} each round's basket, kept names first
 */
export function selectBaskets(rounds, topN) {
  const baskets = [];
  let held = [];
  for (const { candidates, keep } of rounds) {
    if (!keep) {
      held = candidates.slice(0, topN);
    } else {
      const kept = held.filter((symbol) => keep.has(symbol));
      const taken = new Set(kept);
      const fresh = candidates.filter((symbol) => !taken.has(symbol)).slice(0, Math.max(0, topN - kept.length));
      held = [...kept, ...fresh];
    }
    baskets.push(held);
  }
  return baskets;
}

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
 * @param {boolean} [backtest] the ranking came from `simulated_rankings`
 * @returns {string | null}
 */
export function modelForDate(market, date, backtest = false) {
  // Backtest rankings were all produced by today's weights, over the period
  // those weights were fitted on; the label has to say both.
  if (backtest) return "Model 5.1 backtest";
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

  // Each position carries its cost basis (average cost) and the gains it has
  // booked while held: a rebalance that trims a winner back to equal weight
  // sells part of it, which books that part's gain. Together they split the
  // return into booked and open without changing it.
  /** @type {Map<string, {units: number | null, pending: number | null, since: string, entry: {time: string, close: number} | null, basis: number, booked: number}>} */
  let positions = new Map();
  let cash = 1;
  let costsPaid = 0;
  const curve = [];
  const trades = [];
  const closed = [];
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
    // A round with no names -- a filter nothing passed that day -- sells
    // everything and holds cash until a later round has names again, rather
    // than silently keeping stocks the filter no longer selects.
    if (round) {
      let before = cash;
      const current = new Map();
      for (const [symbol, position] of positions) {
        const held = valueOf(symbol, position);
        current.set(symbol, held);
        before += held;
      }
      const targets = new Set(round.symbols);
      const share = targets.size ? before / targets.size : 0;
      // Cash is not a position: moving into or out of it is the trade.
      let traded = 0;
      for (const symbol of new Set([...targets, ...current.keys()])) {
        traded += Math.abs((targets.has(symbol) ? share : 0) - (current.get(symbol) ?? 0));
      }
      const charged = traded * cost;
      costsPaid += charged;
      const each = targets.size ? (before - charged) / targets.size : 0;

      const next = new Map();
      for (const symbol of round.symbols) {
        const held = positions.get(symbol);
        const close = lastClose(symbol);
        if (held && held.pending === null) {
          const units = each / close.close;
          let { basis, booked } = held;
          if (units < held.units) {
            const kept = units / held.units;
            booked += (held.units - units) * close.close - basis * (1 - kept);
            basis *= kept;
          } else {
            basis += (units - held.units) * close.close;
          }
          next.set(symbol, { ...held, units, basis, booked });
        } else if (held) {
          // Still waiting in cash: nothing was bought, so nothing is booked.
          next.set(symbol, { ...held, pending: each, basis: each });
        } else if (close && close.time === time) {
          next.set(symbol, { units: each / close.close, pending: null, since: time, entry: close, basis: each, booked: 0 });
        } else {
          next.set(symbol, { units: null, pending: each, since: time, entry: null, basis: each, booked: 0 });
        }
      }
      // A name the new round drops is sold at its latest close; that is the
      // end of one position, whatever weight resets it went through while held.
      for (const [symbol, position] of positions) {
        if (targets.has(symbol)) continue;
        const booked = position.booked + current.get(symbol) - position.basis;
        closed.push({ symbol, since: position.since, entry: position.entry, exit: lastClose(symbol), soldOn: time, booked });
      }
      trades.push({
        rankDate: round.rankDate ?? null,
        entrySession: time,
        bought: round.symbols.filter((symbol) => !positions.has(symbol)),
        sold: [...positions.keys()].filter((symbol) => !targets.has(symbol)),
        costPct: before > 0 ? (charged / before) * 100 : 0,
        // Portfolio value either side of the round's trades, so each period's
        // return can be measured from one rebalance to the next.
        valueBefore: before,
        valueAfter: before - charged,
      });
      positions = next;
      cash = targets.size ? 0 : before - charged;
    }

    let invested = 0;
    for (const [symbol, position] of positions) invested += valueOf(symbol, position);
    value = cash + invested;
    // As if sold that day, so the last point is the headline number. Cash
    // needs no sale, so only the invested part pays the exit cost.
    curve.push({ time, value: (cash + invested * (1 - cost) - 1) * 100 });
  }

  // Every figure in points of the starting capital, so they add up:
  // booked + open - costs is the curve's last point. Booked is every sale's
  // gain over its average cost, trims included; open is what the holdings
  // are up on theirs; costs are the ones paid plus selling everything today.
  let open = 0;
  let booked = 0;
  for (const position of closed) booked += position.booked;
  for (const [symbol, position] of positions) {
    open += valueOf(symbol, position) - position.basis;
    booked += position.booked;
  }
  const pnl = {
    bookedPct: booked * 100,
    openPct: open * 100,
    costsPct: (costsPaid + (value - cash) * cost) * 100,
    paidPct: costsPaid * 100,
  };

  return { curve, trades, closed, positions, value, lastClose, pnl };
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
    return {
      curve: [],
      grossCurve: [],
      trades: [],
      closedTrades: [],
      stocks: [],
      grossPct: null,
      netPct: null,
      pnl: null,
      grossPnl: null,
    };
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
  // A position's gain still open, in points of the starting capital. Both
  // runs', so the column adds up to the summary with costs on or off.
  const openGain = (run, symbol) => {
    const position = run.positions.get(symbol);
    if (!position) return null;
    const value = position.pending !== null ? position.pending : position.units * run.lastClose(symbol).close;
    return (value - position.basis) * 100;
  };
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
      openPts: openGain(net, symbol),
      grossOpenPts: openGain(gross, symbol),
    };
  });

  // Each round's period runs from just after its trades to just before the
  // next round's, so it measures what that basket did in the market; the
  // round's trading cost is reported beside it rather than inside it.
  const trades = net.trades.map((trade, index) => {
    const end = index + 1 < net.trades.length ? net.trades[index + 1].valueBefore : net.value;
    const periodEnd = index + 1 < net.trades.length ? net.trades[index + 1].entrySession : asOf;
    return {
      rankDate: trade.rankDate,
      entrySession: trade.entrySession,
      periodEnd,
      bought: trade.bought,
      sold: trade.sold,
      costPct: trade.costPct,
      returnPct: trade.valueAfter > 0 ? (end / trade.valueAfter - 1) * 100 : null,
    };
  });

  // Finished positions: bought at one round's fill, sold at a later round.
  // A price-to-price return, like a broker's contract note: it ignores the
  // equal-weight trims and top-ups in between and the trading costs, both of
  // which the basket-level figures carry.
  // Both runs close the same positions in the same order, so the gross
  // booked gain of a position is the gross run's entry at the same index.
  const closedTrades = net.closed.map((position, index) => ({
    symbol: position.symbol,
    bookedPts: position.booked * 100,
    grossBookedPts: gross.closed[index].booked * 100,
    boughtRound: position.since,
    entry: position.entry,
    exit: position.entry ? position.exit : null,
    soldOn: position.soldOn,
    returnPct:
      position.entry && position.exit ? (position.exit.close / position.entry.close - 1) * 100 : null,
  }));

  return {
    curve: net.curve,
    // Both, so a reader can switch costs on and off without another request.
    grossCurve: gross.curve,
    trades,
    closedTrades,
    stocks,
    grossPct: (gross.value - 1) * 100,
    netPct: net.curve.length ? net.curve[net.curve.length - 1].value : null,
    pnl: net.pnl,
    grossPnl: gross.pnl,
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
 * Compound the daily equal-weight universe index over a holding window.
 *
 * Returns accrue on sessions after the entry session, matching a basket bought
 * at that session's close. `through` is the last session the index covers,
 * which trails `asOf` only when the latest run has not been indexed yet.
 *
 * @param {{observed_on: string, ew_return_pct: number}[]} rows ascending
 * @param {{entrySession: string, asOf: string}} window
 * @returns {{returnPct: number | null, through: string | null, sessions: number}}
 */
export function compoundIndex(rows, { entrySession, asOf }) {
  let growth = 1;
  let through = null;
  let sessions = 0;
  for (const row of rows ?? []) {
    if (row.observed_on <= entrySession || row.observed_on > asOf) continue;
    const move = Number(row.ew_return_pct);
    if (!Number.isFinite(move)) continue;
    growth *= 1 + move / 100;
    through = row.observed_on;
    sessions += 1;
  }
  return { returnPct: sessions ? (growth - 1) * 100 : null, through, sessions };
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
  { label: "3Y", months: 36 },
  { label: "5Y", months: 60 },
  { label: "All", months: null },
];
