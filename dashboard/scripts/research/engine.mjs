// Shared study machinery: the Returns page's own selection rules and engine
// (lib/returns.mjs), run on data cached by data.mjs.
import { readFileSync } from "node:fs";

import { out } from "./paths.mjs";
import {
  RATING_PICKS, STAGE_PICKS, pickKey, pickOption, selectBaskets, rebalanceDates, rebalanceOption,
  entrySessionAfter, snapRankingDate, portfolioReturns, COST_PER_SIDE_PCT,
} from "../../lib/returns.mjs";

export function loadData(end) {
  const d = JSON.parse(readFileSync(out(`data-${end}.json`), "utf8"));
  const byDate = new Map();
  for (const r of d.rankings) {
    if (!byDate.has(r.observed_on)) byDate.set(r.observed_on, []);
    byDate.get(r.observed_on).push(r);
  }
  const states = new Map(d.states.map((s) => [s.observed_on, { advancing: new Set(s.advancing ?? []), buy_plus: new Set(s.buy_plus ?? []) }]));
  const closes = new Map(Object.entries(d.closes).map(([s, pts]) => [s, pts.map(([time, close]) => ({ time, close }))]));
  const dates = [...byDate.keys()].sort();
  const asOf = d.sessions[d.sessions.length - 1];
  return { ...d, byDate, states, closes, dates, asOf };
}

export const PICKS = RATING_PICKS.flatMap((r) => STAGE_PICKS.map((s) => pickKey(r.value, s.value)));

/** The buy list for one date, exactly as getRankingTops builds it for backtest dates. */
export function listFor(data, date, pick, topN) {
  const rows = data.byDate.get(date) ?? [];
  const filtered = pick.columns.length > 0;
  const depth = filtered ? Math.min(50, topN * 2) : topN;
  if (!filtered) return rows.filter((r) => r.investment_rank <= topN).sort((a, b) => a.investment_rank - b.investment_rank);
  if (pick.columns.length === 1) {
    const c = pick.columns[0];
    return rows.filter((r) => r[c] != null && r[c] <= depth).sort((a, b) => a[c] - b[c]);
  }
  const pass = rows.filter((r) =>
    (!pick.ratings || pick.ratings.includes(r.rating)) &&
    (!pick.stage || r.stage === pick.stage) &&
    (!pick.maxAdvanceAge || (r.advance_age_days != null && r.advance_age_days <= pick.maxAdvanceAge)));
  const cutoff = Math.max(...pick.columns.map((c) => rows.find((r) => r[c] === 50)?.investment_rank ?? Infinity));
  return pass.filter((r) => r.investment_rank <= cutoff).sort((a, b) => a.investment_rank - b.investment_rank).slice(0, depth);
}

const firstRatedCache = new WeakMap();

/** A config may carry its own `asOf`, the end of its window; otherwise the data's end. */
export function roundsFor(data, { pick: key, topN, rebalance, from, asOf = data.asOf }) {
  const pick = pickOption(key);
  let start = snapRankingDate(data.dates, from);
  if (pick.ratings) {
    if (!firstRatedCache.has(data)) {
      firstRatedCache.set(data, data.dates.find((date) => (data.byDate.get(date) ?? []).some((r) => r.rating)));
    }
    const firstRated = firstRatedCache.get(data);
    if (start < firstRated) start = firstRated;
  }
  const schedule = rebalanceDates(data.dates, start, rebalanceOption(rebalance))
    .filter((date) => date <= asOf && (entrySessionAfter(data.sessions, date) ?? "9999") <= asOf);
  const candidates = schedule.map((date) => listFor(data, date, pick, topN).map((r) => r.symbol));
  const keeps = schedule.map((date) => {
    if (!pick.holds.length) return null;
    const sets = pick.holds.map((h) => data.states.get(date)?.[h] ?? new Set());
    return new Set([...sets[0]].filter((s) => sets.every((set) => set.has(s))));
  });
  const baskets = selectBaskets(candidates.map((c, i) => ({ candidates: c, keep: keeps[i] })), topN);
  return schedule.map((date, i) => ({ rankDate: date, entrySession: entrySessionAfter(data.sessions, date), symbols: baskets[i] }));
}

export function metrics(curve) {
  if (!curve.length) return null;
  const w = curve.map((p) => 1 + p.value / 100);
  const days = (Date.parse(curve.at(-1).time) - Date.parse(curve[0].time)) / 864e5;
  const years = days / 365.25;
  let peak = w[0], maxDD = 0, longest = 0, peakTime = curve[0].time;
  for (let i = 0; i < w.length; i++) {
    if (w[i] >= peak) { peak = w[i]; peakTime = curve[i].time; }
    maxDD = Math.min(maxDD, w[i] / peak - 1);
    longest = Math.max(longest, (Date.parse(curve[i].time) - Date.parse(peakTime)) / 864e5);
  }
  const rets = w.slice(1).map((x, i) => x / w[i] - 1);
  const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
  const sd = Math.sqrt(rets.reduce((a, b) => a + (b - mean) ** 2, 0) / rets.length);
  const cagr = w.at(-1) ** (1 / years) - 1;
  const byYear = {};
  let prev = 1;
  for (let i = 0; i < curve.length; i++) {
    const y = curve[i].time.slice(0, 4);
    const next = curve[i + 1]?.time.slice(0, 4);
    if (next !== y) { byYear[y] = (w[i] / prev - 1) * 100; prev = w[i]; }
  }
  return {
    totalPct: (w.at(-1) - 1) * 100, cagrPct: cagr * 100, maxDDPct: maxDD * 100, longestUnderwaterDays: Math.round(longest),
    volPct: sd * Math.sqrt(252) * 100, sharpe: sd ? (mean * 252) / (sd * Math.sqrt(252)) : null,
    calmar: maxDD ? cagr / -maxDD : null, years, byYear,
  };
}

export function benchmarkCurve(data, from, to) {
  const pts = data.benchmark.filter((p) => p.time >= from && p.time <= to);
  return pts.map((p) => ({ time: p.time, value: (p.value / pts[0].value - 1) * 100 }));
}

export function run(data, config) {
  const rounds = roundsFor(data, config);
  const asOf = config.asOf ?? data.asOf;
  const result = portfolioReturns(rounds, data.closes, { asOf, costPerSidePct: COST_PER_SIDE_PCT, slots: config.topN, weights: config.weights });
  const m = metrics(result.curve, null);
  const closed = result.closedTrades.filter((t) => t.returnPct !== null);
  const wins = closed.filter((t) => t.returnPct > 0).length;
  const sorted = closed.map((t) => t.returnPct).sort((a, b) => a - b);
  const short = rounds.filter((r) => r.symbols.length < config.topN).length;
  const empty = rounds.filter((r) => r.symbols.length === 0).length;
  return {
    ...config, start: rounds[0]?.entrySession, end: asOf, rounds: rounds.length, shortRounds: short, emptyRounds: empty,
    trades: closed.length, winRate: closed.length ? (wins / closed.length) * 100 : null,
    medianTrade: sorted.length ? sorted[Math.floor(sorted.length / 2)] : null,
    worstTrade: sorted[0] ?? null, costsPct: result.pnl?.costsPct ?? null,
    ...m, curve: result.curve,
  };
}

export function episodes(curve, n = 4) {
  const w = curve.map((p) => 1 + p.value / 100);
  const eps = []; let peak = 0;
  for (let i = 1; i <= w.length; i++) {
    if (i === w.length || w[i] >= w[peak]) {
      let trough = peak; for (let j = peak; j < i; j++) if (w[j] < w[trough]) trough = j;
      if (trough > peak) eps.push({ peak: curve[peak].time, trough: curve[trough].time, recovered: i < w.length ? curve[i].time : null, dd: (w[trough] / w[peak] - 1) * 100 });
      peak = i;
    }
  }
  return eps.sort((a, b) => a.dd - b.dd).slice(0, n);
}

/** screener/benchmark.py classify_regime, on levels up to and including `date`. */
export function regimeAt(levels, date, { ma = 200, slope = 20, band = 2 } = {}) {
  let end = -1;
  for (let i = 0; i < levels.length && levels[i].time <= date; i++) end = i;
  if (end + 1 < ma + slope) return "UNKNOWN";
  const avg = (last) => { let s = 0; for (let i = last - ma + 1; i <= last; i++) s += levels[i].value; return s / ma; };
  const now = avg(end), then = avg(end - slope);
  const distance = (levels[end].value / now - 1) * 100, slopePct = (now / then - 1) * 100;
  if (distance > band && slopePct > 0) return "RISK_ON";
  if (distance < -band && slopePct < 0) return "RISK_OFF";
  return "NEUTRAL";
}

export function runRules(data, { base, rules, from, asOf = data.asOf }) {
  const start = snapRankingDate(data.dates, from);
  // Rules are checked weekly whatever the ranking cadence: the backtest ranks
  // weekly, but published rankings are daily.
  // (One check per calendar week: the first ranking of each Monday-to-Sunday week.)
  const weekOf = (d) => { const t = new Date(d + "T00:00:00Z"); t.setUTCDate(t.getUTCDate() - ((t.getUTCDay() + 6) % 7)); return t.toISOString().slice(0, 10); };
  const seen = new Set();
  const weeks = data.dates.filter((d) => {
    if (d < start || (entrySessionAfter(data.sessions, d) ?? "9999") > asOf || seen.has(weekOf(d))) return false;
    seen.add(weekOf(d));
    return true;
  });
  const rebalance = new Set(rebalanceDates(weeks, start, rebalanceOption(base.rebalance)));
  const top = (d) => (data.byDate.get(d) ?? []).filter((r) => r.investment_rank <= base.topN).sort((a, b) => a.investment_rank - b.investment_rank).map((r) => r.symbol);
  const switches = [rules.includes("R1") && data.benchmark, rules.includes("R2") && data.smallcap].filter(Boolean);
  const rounds = [];
  let invested = false, offWeeks = 0, flips = 0;
  for (const d of weeks) {
    const off = switches.some((levels) => regimeAt(levels, d) === "RISK_OFF");
    if (off) offWeeks++;
    if (off && invested) { rounds.push({ rankDate: d, symbols: [] }); invested = false; flips++; }
    else if (!off && (!invested || rebalance.has(d))) { if (!invested && rounds.length) flips++; rounds.push({ rankDate: d, symbols: top(d) }); invested = true; }
  }
  for (const r of rounds) r.entrySession = entrySessionAfter(data.sessions, r.rankDate);
  const firstEntry = entrySessionAfter(data.sessions, start);
  const result = portfolioReturns(rounds, data.closes, {
    asOf, costPerSidePct: COST_PER_SIDE_PCT, slots: base.topN, weights: base.weights,
    trailingStopPct: rules.includes("R3") ? 20 : null,
    investedPct: base.investedPct ?? 100,
  });
  // Weeks in cash before the first purchase count as flat, from the same start.
  const curve = result.curve[0]?.time > firstEntry ? [{ time: firstEntry, value: 0 }, ...result.curve] : result.curve;
  return { ...metrics(curve), curve, offShare: (offWeeks / weeks.length) * 100, flips, stops: result.stops.length, costsPct: result.pnl.costsPct, start: firstEntry };
}

