// A score the viewer builds: their own weights over measures every viewer can
// already see. It is the viewer's method, not the model's, so it never reads
// the model's score, rank, weights or gates (lib/ratings.mjs), and it ships no
// weights of its own beyond an equal split to start from.

/**
 * The measures a viewer can weight, each 0-100 with higher read as stronger.
 * The one source of each measure's name and plain meaning: the builder, the
 * grid's headers and the stock page's profile all read `label`, `caption` and
 * `about` from here (words follow screener/factors.py). `block` is the factor
 * block's key where the measure is one (lib/types.ts FACTOR_BLOCKS).
 */
const CALL_COLUMN = "call_signal";

export const SCORE_FACTORS = [
  {
    key: "q", column: "quality_score", block: "quality", label: "Quality",
    caption: "Earns well on its money, low debt",
    about: "How good the business is at making money from the money it uses: returns on capital, how much profit turns into real cash, how much it borrows and how steady its profits have been. Higher means stronger on these facts than other companies on the list.",
  },
  {
    key: "g", column: "growth_score", block: "growth", label: "Growth",
    caption: "Sales and profit rising, and faster",
    about: "How fast sales and profit have grown over three years, whether that growth is speeding up, whether margins are widening and whether cash backs the profit. The latest quarter against a year earlier counts too. Higher means faster, better-backed growth than other companies on the list.",
  },
  {
    key: "m", column: "momentum_score", block: "momentum", label: "Momentum",
    caption: "Share price rising more than most",
    about: "How strongly the share price has risen over the past six and twelve months (leaving out the latest month), allowing for how bumpy the ride was, against its sector and the market. Higher means a stronger price trend than other stocks. Past moves do not predict future ones.",
  },
  {
    key: "v", column: "value_score", block: "value", label: "Value",
    caption: "Cheap for the profit and cash it makes",
    about: "How much you get for the share price: profit, free cash, operating earnings and book assets per unit of price, plus a fair-value estimate. Higher means cheaper on these measures than other companies. Cheap can be cheap for a reason; look at Quality beside it.",
  },
  {
    // risk_score is high when prices are calm (screener/factors.py RISK_FEATURES), so it reads as Steadiness.
    key: "r", column: "risk_score", block: "risk", label: "Steadiness",
    caption: "Calmer prices, smaller falls",
    about: "How calm the share price has been over the past year: smaller daily swings, shallower falls from its peak, fewer sudden gaps, and trading on most days. Higher means steadier than other stocks. A steady past does not promise a steady future.",
  },
  {
    key: "rs", column: "rs_rating", label: "Price strength",
    caption: "Recent returns against every stock",
    about: "A 1-99 rating of the share's return over the last 3, 6, 9 and 12 months (the latest three months count double), ranked against every stock on the list. 80 means it did better than about 80% of them.",
  },
  {
    // `derived`: not a snapshot column (never select it); callSignals works it out per run from tone and outlook.
    key: "c", column: CALL_COLUMN, derived: true, label: "Earnings call", concall: true, toggle: true,
    caption: "How upbeat and confident the latest earnings call was",
    about: "How positive management sounded on its latest earnings call: mostly what it said about the outlook, partly the tone of its words, against every other recent call. A call counts half after 90 days and not at all after 180; no recent call counts as middle of the pack. Words, not results.",
  },
];

/** Points added on top of the blend's run percentile: `d` / 100 per point of valuation score away from 50. */
export const POINT_FACTORS = [
  {
    key: "d", label: "Fair-value nudge",
    caption: "Lifts stocks priced below a fair-value estimate, lowers those above",
    about: "Adds a little to stocks priced below a fair-value estimate (a discounted cash-flow model) and takes a little from those above. Only stocks the model fits get a nudge. It changes the order; it is not a price target.",
  },
];

/** A factor block's measure (quality, growth, momentum, value, risk), for the grid and the stock page. */
export function blockFactor(block) {
  return SCORE_FACTORS.find((factor) => factor.block === block) ?? null;
}

/** A percentile in words: 72 -> "Ahead of 72% of stocks". */
export function aheadOf(percentile) {
  const value = num(percentile);
  return value === null ? null : `Ahead of ${Math.round(value)}% of stocks`;
}

/**
 * How much a measure counts, in words. The URL keeps the number (`w=q35`); a
 * value between two steps (an older link) reads as the nearer one and is kept
 * until the viewer moves it.
 */
export const IMPORTANCE = [
  { label: "Ignore", value: 0 },
  { label: "A little", value: 10 },
  { label: "Some", value: 20 },
  { label: "A lot", value: 35 },
  { label: "Most", value: 50 },
];

/** An extra nudge's size, in words; `d` keeps its number in the URL. */
export const NUDGE = [
  { label: "Off", value: 0 },
  { label: "Light", value: 25 },
  { label: "Strong", value: 50 },
];

/** The nudge step nearest `value` (ties go to the lower step). */
export function nudgeStep(value) {
  return nearest(NUDGE, value);
}

function nearest(steps, value) {
  const weight = num(value) ?? 0;
  let best = 0;
  for (let at = 1; at < steps.length; at++) {
    if (Math.abs(steps[at].value - weight) < Math.abs(steps[best].value - weight)) best = at;
  }
  return best;
}

/** The step nearest `value` (ties go to the lower step). */
export function importanceStep(value) {
  return nearest(IMPORTANCE, value);
}

/**
 * Each weighted measure's share of the mix, in the factors' order, as whole
 * percents that add to 100 (largest remainder); empty when nothing is weighted.
 * @param {Record<string, number>} weights
 * @param {{ key: string }[]} factors
 */
export function mixShares(weights, factors) {
  const used = factors.filter((factor) => (weights[factor.key] ?? 0) > 0);
  const total = used.reduce((sum, factor) => sum + weights[factor.key], 0);
  if (!total) return [];
  const exact = used.map((factor) => ({ key: factor.key, exact: (weights[factor.key] / total) * 100 }));
  const shares = exact.map((entry) => ({ key: entry.key, share: Math.floor(entry.exact) }));
  let left = 100 - shares.reduce((sum, entry) => sum + entry.share, 0);
  const order = exact.map((entry, at) => ({ at, rest: entry.exact % 1 })).sort((a, b) => b.rest - a.rest || a.at - b.at);
  for (const { at } of order) {
    if (left <= 0) break;
    shares[at].share += 1;
    left -= 1;
  }
  return shares;
}

/** What a screen reader hears for one measure: "Momentum: A lot, 30% of your mix". */
export function importanceText(label, weight, share) {
  const step = IMPORTANCE[importanceStep(weight)].label;
  return weight > 0 ? `${label}: ${step}, ${share}% of your mix` : `${label}: ${step}`;
}

/** Every column scoreRun reads besides the outlook. */
export const RUN_COLUMNS = [
  "symbol",
  ...SCORE_FACTORS.filter((f) => !("derived" in f)).map((f) => f.column),
  "dcf_valuation_score",
  "dcf_blend_eligible",
  "transcript_score",
  "transcript_scoring_eligible",
  "transcript_age_days",
];

/** Where the builder starts: the five factors equally, nothing else. */
export const EQUAL_START = { q: 20, g: 20, m: 20, v: 20, r: 20, rs: 0, c: 0 };

/**
 * `q20.g20.m30` -> { q: 20, g: 20, m: 30 }; null when no factor has a positive weight.
 * @param {string | null | undefined} text
 * @returns {Record<string, number> | null}
 */
export function parseWeights(text) {
  if (!text) return null;
  /** @type {Record<string, number>} */
  const weights = {};
  for (const part of String(text).split(".")) {
    const match = /^([a-z]+)(\d{1,3})$/.exec(part);
    if (!match) continue;
    const value = Math.min(100, Number(match[2]));
    // Older links: call tone (`t`) and the call nudge (`c`, 25 or 50) are now the one Earnings call measure, at the nearer step.
    if (match[1] === "t" || match[1] === "c") {
      if (value > 0) weights.c = Math.max(weights.c ?? 0, IMPORTANCE[importanceStep(value)].value);
      continue;
    }
    const factor = [...SCORE_FACTORS, ...POINT_FACTORS].find((f) => f.key === match[1]);
    if (factor && value > 0) weights[factor.key] = value;
  }
  return Object.keys(weights).length ? weights : null;
}

/**
 * The URL form of a mix, factors in their fixed order, zero weights left out.
 * @param {Record<string, number>} weights
 */
export function formatWeights(weights) {
  return [...SCORE_FACTORS, ...POINT_FACTORS].filter((f) => (weights[f.key] ?? 0) > 0)
    .map((f) => `${f.key}${Math.round(weights[f.key])}`)
    .join(".");
}

/**
 * The viewer's score for one row, 0-100.
 *
 * Absent evidence is not a zero: a measure the row lacks leaves both the sum
 * and its weight, and the result is shrunk toward 50 by the share of weight
 * that was observed. Null when the row has none of the weighted measures.
 * @param {Record<string, unknown>} row
 * @param {Record<string, number>} weights
 * @returns {number | null}
 */
export function weightedScore(row, weights) {
  let total = 0;
  let covered = 0;
  let sum = 0;
  for (const factor of SCORE_FACTORS) {
    const weight = weights[factor.key] ?? 0;
    if (weight <= 0) continue;
    total += weight;
    const value = row[factor.column];
    if (value === null || value === undefined || !Number.isFinite(Number(value))) continue;
    covered += weight;
    sum += weight * Number(value);
  }
  if (!covered) return null;
  const raw = sum / covered;
  return 50 + (raw - 50) * (covered / total);
}

const num = (value) => (value === null || value === undefined || value === "" || !Number.isFinite(Number(value)) ? null : Number(value));

/**
 * A call's weight by age: halves every 90 days, nothing past 180.
 * shortcut: leaves out the taper near a quarter's turn; add it if the lists drift then.
 * @param {unknown} ageDays
 */
export function concallRecency(ageDays) {
  const age = num(ageDays);
  if (age === null || age > 180) return 0;
  return Math.exp((-Math.LN2 * Math.max(0, age)) / 90);
}

/**
 * Each recent call's Earnings call value by symbol, 0-100: 85% outlook plus 15%
 * tone, ranked across the run's eligible calls (the outlook's own level sits
 * well above 50, so the rank is what reads as "more upbeat than most"), then
 * faded toward 50 by age (concallRecency). No eligible call within 180 days: no value.
 * @param {Record<string, unknown>[]} rows
 * @param {Map<string, number>} outlooks latest outlook score by symbol
 * @returns {Map<string, number>}
 */
export function callSignals(rows, outlooks) {
  const calls = [];
  for (const row of rows) {
    if (row.transcript_scoring_eligible !== true) continue;
    const tone = num(row.transcript_score);
    const outlook = outlooks.get(String(row.symbol));
    const recency = concallRecency(row.transcript_age_days);
    if (tone === null || outlook === undefined || !recency) continue;
    calls.push({ symbol: String(row.symbol), blend: Math.round((0.15 * tone + 0.85 * outlook) * 100) / 100, recency });
  }
  const percentile = percentiles(calls.map((call) => call.blend));
  return new Map(calls.map((call) => [call.symbol, 50 + call.recency * (percentile(call.blend) - 50)]));
}

/**
 * The arithmetic under the viewer's score, before scoreRun ranks it.
 *
 * The weighted blend (Earnings call included, from callSignals) is ranked
 * across the run onto 0-100 ((rank - 1) / (n - 1), ties averaged); `d` / 100
 * points per point of valuation score away from 50 are then added. Pass the
 * whole run: a percentile of a filtered subset is a different number.
 * @param {Record<string, unknown>[]} rows
 * @param {Record<string, number>} weights
 * @param {Map<string, number>} [outlooks] latest outlook score by symbol
 * @returns {Map<string, number | null>}
 */
export function rawScores(rows, weights, outlooks = new Map()) {
  const signals = (weights.c ?? 0) > 0 ? callSignals(rows, outlooks) : null;
  const blends = rows.map((row) => {
    const blend = weightedScore(signals ? { ...row, [CALL_COLUMN]: signals.get(String(row.symbol)) } : row, weights);
    return blend === null ? null : Math.round(blend * 100) / 100;
  });
  const percentile = percentiles(blends);

  const dcfPoints = (weights.d ?? 0) / 100;

  return new Map(
    rows.map((row, index) => {
      const blend = blends[index];
      if (blend === null) return [String(row.symbol), null];
      let score = percentile(blend);
      const dcf = num(row.dcf_valuation_score);
      if (dcfPoints && dcf !== null && row.dcf_blend_eligible === true) {
        score += dcfPoints * (dcf - 50);
      }
      return [String(row.symbol), score];
    }),
  );
}

/**
 * Each value's percentile across the non-null values, 0 (lowest) to 100
 * (highest), ties averaged; a lone value is 50.
 * @param {(number | null)[]} values
 * @returns {(value: number) => number}
 */
function percentiles(values) {
  const sorted = /** @type {number[]} */ (values.filter((v) => v !== null)).sort((x, y) => x - y);
  const n = sorted.length;
  /** @type {Map<number, number>} */
  const ranks = new Map();
  for (let lo = 0; lo < n; ) {
    let hi = lo;
    while (hi + 1 < n && sorted[hi + 1] === sorted[lo]) hi++;
    ranks.set(sorted[lo], n < 2 ? 50 : ((lo + hi) / 2 / (n - 1)) * 100);
    lo = hi + 1;
  }
  return (value) => /** @type {number} */ (ranks.get(value));
}

/**
 * The viewer's score: where their mix, plus any nudge points, lands among
 * every scored stock of the run, 0 (last) to 100 (first). Nudges move a
 * stock along that line; they never push it past either end or tie the top.
 * Without a nudge this is the blend's percentile, unchanged.
 * @param {Record<string, unknown>[]} rows
 * @param {Record<string, number>} weights
 * @param {Map<string, number>} [outlooks] latest outlook score by symbol
 * @returns {Map<string, number | null>}
 */
export function scoreRun(rows, weights, outlooks = new Map()) {
  const raw = rawScores(rows, weights, outlooks);
  if (!(weights.d ?? 0)) return raw;
  const values = [...raw.values()].map((v) => (v === null ? null : Math.round(v * 100) / 100));
  const percentile = percentiles(values);
  return new Map([...raw.keys()].map((symbol, i) => [symbol, values[i] === null ? null : percentile(/** @type {number} */ (values[i]))]));
}

/**
 * Symbols ordered by score, highest first; unscored last, ties by symbol.
 * @param {Map<string, number | null>} scores
 * @param {Iterable<string>} symbols
 * @returns {{ symbol: string, score: number | null }[]}
 */
export function rankScores(scores, symbols) {
  return [...symbols]
    .map((symbol) => ({ symbol, score: scores.get(symbol) ?? null }))
    .sort((a, b) => {
      if (a.score === null || b.score === null) {
        if (a.score === b.score) return a.symbol < b.symbol ? -1 : 1;
        return a.score === null ? 1 : -1;
      }
      return b.score - a.score || (a.symbol < b.symbol ? -1 : 1);
    });
}

/**
 * The first `size` scored rows of the run by `weights`, as the builder's
 * preview lists them; recomputed from scratch for every mix.
 * @param {Record<string, unknown>[]} rows
 * @param {Record<string, number>} weights
 * @param {Map<string, number>} [outlooks]
 * @param {number} [size]
 * @returns {{ symbol: string, company: string | null, score: number }[]}
 */
export function topByMix(rows, weights, outlooks = new Map(), size = 5) {
  const companies = new Map(rows.map((row) => [String(row.symbol), /** @type {string | null} */ (row.company ?? null)]));
  return rankScores(scoreRun(rows, weights, outlooks), companies.keys())
    .slice(0, size)
    .flatMap((entry) => (entry.score === null ? [] : [{ symbol: entry.symbol, company: companies.get(entry.symbol) ?? null, score: entry.score }]));
}

/**
 * What made a row's blend, for the Your score cell: each weighted measure the
 * row has, with its value and its part of the blend (weight x value over the
 * sum of those), largest first. Empty when the row has none of them.
 * @param {Record<string, unknown>} row
 * @param {Record<string, number>} weights
 * @returns {{ key: string, label: string, value: number, part: number }[]}
 */
export function scoreDrivers(row, weights) {
  const parts = [];
  for (const factor of SCORE_FACTORS) {
    const weight = weights[factor.key] ?? 0;
    const value = num(row[factor.column]);
    if (weight > 0 && value !== null) parts.push({ key: factor.key, label: factor.label, value, raw: weight * Math.max(0, value) });
  }
  const total = parts.reduce((sum, entry) => sum + entry.raw, 0);
  return parts
    .map(({ raw, ...entry }) => ({ ...entry, part: total ? raw / total : 0 }))
    .sort((a, b) => b.part - a.part);
}

/** "Mostly Momentum (82) and Quality (74)." for a cell's tooltip; null with no drivers. */
export function driversText(drivers) {
  const [first, second] = drivers;
  if (!first) return null;
  const named = (entry) => `${entry.label} (${Math.round(entry.value)})`;
  return second ? `Mostly ${named(first)} and ${named(second)}.` : `All ${named(first)}.`;
}
