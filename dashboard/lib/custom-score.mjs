// A score the viewer builds: their own weights over measures every viewer can
// already see. It is the viewer's method, not the model's, so it never reads
// the model's score, rank, weights or gates (lib/ratings.mjs), and it ships no
// weights of its own beyond an equal split to start from.

/** The measures a viewer can weight, each 0-100 with higher read as stronger. */
export const SCORE_FACTORS = [
  { key: "q", column: "quality_score", label: "Quality" },
  { key: "g", column: "growth_score", label: "Growth" },
  { key: "m", column: "momentum_score", label: "Momentum" },
  { key: "v", column: "value_score", label: "Value" },
  { key: "r", column: "risk_score", label: "Risk" },
  { key: "rs", column: "rs_rating", label: "RS rating" },
  // The call's word-list tone; the outlook enters only as points (CONCALL below).
  { key: "t", column: "transcript_score", label: "Concall tone" },
];

/**
 * Points added on top of the blend's run percentile, each weight / 100 points per
 * point of distance: `d` from a neutral 50 valuation, `c` from the run's median call.
 */
export const POINT_FACTORS = [
  { key: "d", label: "Valuation points (vs 50)" },
  { key: "c", label: "Concall points (vs median)" },
];

/** Every column scoreRun reads besides the outlook. */
export const RUN_COLUMNS = [
  "symbol",
  ...SCORE_FACTORS.map((f) => f.column),
  "dcf_valuation_score",
  "dcf_blend_eligible",
  "transcript_scoring_eligible",
  "transcript_age_days",
];

/** Where the builder starts: the five factors equally, nothing else. */
export const EQUAL_START = { q: 20, g: 20, m: 20, v: 20, r: 20, rs: 0, t: 0 };

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
    const factor = [...SCORE_FACTORS, ...POINT_FACTORS].find((f) => f.key === match[1]);
    const value = Math.min(100, Number(match[2]));
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

/** @param {number[]} values */
function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

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
 * The viewer's score for every row of a run.
 *
 * The weighted blend is ranked across the run onto 0-100 ((rank - 1) / (n - 1),
 * ties averaged); points are then added: `d` / 100 per point of valuation score
 * away from 50, and `c` / 100 per point a recent call sits from the run's median
 * call (85% outlook, 15% tone; each median taken over the calls applied, 50
 * below 30 calls). Pass the whole run: a percentile or median of a filtered
 * subset is a different number.
 * @param {Record<string, unknown>[]} rows
 * @param {Record<string, number>} weights
 * @param {Map<string, number>} [outlooks] latest outlook score by symbol
 * @returns {Map<string, number | null>}
 */
export function scoreRun(rows, weights, outlooks = new Map()) {
  const blends = rows.map((row) => {
    const blend = weightedScore(row, weights);
    return blend === null ? null : Math.round(blend * 100) / 100;
  });
  const sorted = /** @type {number[]} */ (blends.filter((b) => b !== null)).sort((a, b) => a - b);
  const n = sorted.length;
  /** @param {number} value */
  const percentile = (value) => {
    if (n < 2) return 50;
    let lo = 0;
    while (sorted[lo] < value) lo++;
    let hi = lo;
    while (hi + 1 < n && sorted[hi + 1] === value) hi++;
    return ((lo + hi) / 2 / (n - 1)) * 100;
  };

  const dcfPoints = (weights.d ?? 0) / 100;
  const callPoints = (weights.c ?? 0) / 100;
  const calls = rows.map((row) => {
    if (!callPoints || row.transcript_scoring_eligible !== true) return null;
    const tone = num(row.transcript_score);
    const outlook = outlooks.get(String(row.symbol));
    const recency = concallRecency(row.transcript_age_days);
    return tone === null || outlook === undefined || !recency ? null : { tone, outlook, recency };
  });
  const applied = /** @type {{ tone: number, outlook: number, recency: number }[]} */ (calls.filter(Boolean));
  const enough = applied.length >= 30;
  const toneMedian = enough ? median(applied.map((c) => c.tone)) : 50;
  const outlookMedian = enough ? median(applied.map((c) => c.outlook)) : 50;

  return new Map(
    rows.map((row, index) => {
      const blend = blends[index];
      if (blend === null) return [String(row.symbol), null];
      let score = percentile(blend);
      const dcf = num(row.dcf_valuation_score);
      if (dcfPoints && dcf !== null && row.dcf_blend_eligible === true) {
        score = Math.min(100, Math.max(0, score + dcfPoints * (dcf - 50)));
      }
      const call = calls[index];
      if (call) {
        score += callPoints * call.recency * (0.15 * (call.tone - toneMedian) + 0.85 * (call.outlook - outlookMedian));
      }
      return [String(row.symbol), score];
    }),
  );
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
