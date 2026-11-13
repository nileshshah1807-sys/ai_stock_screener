// A score the viewer builds: their own weights over measures every viewer can
// already see. It is the viewer's method, not the model's, so it never reads
// the model's score, rank, weights or gates (lib/ratings.mjs), and it ships no
// weights of its own beyond an equal split to start from.

/** The measures a viewer can weight, each 0-100 with higher read as stronger. */
export const SCORE_FACTORS = [
  { key: "q", column: "quality_percentile", label: "Quality" },
  { key: "g", column: "growth_percentile", label: "Growth" },
  { key: "m", column: "momentum_percentile", label: "Momentum" },
  { key: "v", column: "value_percentile", label: "Value" },
  { key: "r", column: "risk_percentile", label: "Risk" },
  { key: "rs", column: "rs_rating", label: "RS rating" },
  { key: "t", column: "transcript_score", label: "Concall outlook" },
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
    const factor = SCORE_FACTORS.find((f) => f.key === match[1]);
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
  return SCORE_FACTORS.filter((f) => (weights[f.key] ?? 0) > 0)
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

/**
 * Rows ordered by the viewer's score, highest first; unscored rows last, ties by symbol.
 * @param {Record<string, unknown>[]} rows
 * @param {Record<string, number>} weights
 * @returns {{ symbol: string, score: number | null }[]}
 */
export function rankByWeights(rows, weights) {
  return rows
    .map((row) => ({ symbol: String(row.symbol), score: weightedScore(row, weights) }))
    .sort((a, b) => {
      if (a.score === null || b.score === null) {
        if (a.score === b.score) return a.symbol < b.symbol ? -1 : 1;
        return a.score === null ? 1 : -1;
      }
      return b.score - a.score || (a.symbol < b.symbol ? -1 : 1);
    });
}
