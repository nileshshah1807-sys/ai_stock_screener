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
 * Whether a run ranked eligibility-first (<= 5.0) or on research merit (5.1+).
 *
 * Read from the run's own policy version rather than assumed, because the older
 * behaviour stays reachable behind RANK_BY_ELIGIBILITY_CLASS and historical
 * snapshots must keep describing themselves correctly.
 *
 * @param {string | null | undefined} policyVersion
 * @returns {boolean}
 */
export function ranksEligibilityFirst(policyVersion) {
  const major = Number.parseInt(String(policyVersion ?? "").split(".")[0], 10);
  const minor = Number.parseInt(String(policyVersion ?? "").split(".")[1], 10);
  if (!Number.isFinite(major) || !Number.isFinite(minor)) return true;
  return major < 5 || (major === 5 && minor < 1);
}

/**
 * @param {boolean} factorModel
 * @param {string | null | undefined} [policyVersion]
 * @returns {string}
 */
export function investmentRankExplanation(factorModel, policyVersion) {
  if (!factorModel) {
    return "Investment Rank is decision-score-first and is the primary order.";
  }
  return ranksEligibilityFirst(policyVersion)
    ? "Investment Rank orders eligibility class first, then the uncapped research score within each class."
    : "Investment Rank orders on research score alone. Eligibility gates are reported, not ranked, so a gated name can rank highly -- check its rating and gate warning before acting.";
}
