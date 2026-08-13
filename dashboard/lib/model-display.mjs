/**
 * Run-aware display decisions shared by the screener list and stock detail.
 *
 * These helpers deliberately consume the values published by the run instead
 * of repeating Config defaults in the UI. A non-default candidate must never
 * be explained as though it used the default weights or score basis.
 */

/**
 * @param {unknown} value
 * @returns {number | null}
 */
export function finiteNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/**
 * @param {Record<string, unknown>} payload
 * @param {string} payloadKey
 * @returns {number | null}
 */
export function publishedFactorWeight(payload, payloadKey) {
  return finiteNumber(payload[payloadKey]);
}

/**
 * @param {number | null} score
 * @param {number | null} weight
 * @returns {number | null}
 */
export function factorContribution(score, weight) {
  return score === null || weight === null ? null : score * weight;
}

/**
 * @param {string | null | undefined} basis
 * @returns {"percentile" | "weighted" | "unknown"}
 */
export function researchScoreMode(basis) {
  if (basis === "cross_sectional_percentile") return "percentile";
  if (basis === "weighted_block_average") return "weighted";
  return "unknown";
}

/**
 * @param {boolean} factorModel
 * @returns {string}
 */
export function investmentRankExplanation(factorModel) {
  return factorModel
    ? "Investment Rank orders eligibility class first, then the uncapped research score within each class."
    : "Investment Rank is decision-score-first and is the primary order.";
}
