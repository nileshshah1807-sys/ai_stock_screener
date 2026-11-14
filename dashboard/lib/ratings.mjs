// Buy/sell ratings are shown to admins only. A paid reader of an Indian
// screener that publishes ratings is buying research, which needs SEBI
// registration (docs/commercialisation_readiness.md); until then a viewer sees
// the evidence -- scores, ranks, stages -- and not the label drawn from it.
//
// Redacted on the server, so the value never reaches a viewer's browser: a
// hidden badge whose rating is still in the page payload is not hidden.

// Besides the labels, this takes every column the label can be read back from:
// Decision_Score (Rating is rating_from_score of it), the eligibility tier, the
// gates and caps, the execution flag and the ranks ordered by rating or
// eligibility. Final_Score, Investment_Rank, Score_Rank and Action_Rank (all
// ordered by evidence, not by rating) stay visible.
// RS_Rating is relative strength, not a buy/sell call. The database applies the
// same rule (is_rating_field in storage/rating_access_schema.sql); the test
// fails if the two drift.
export const RATING_KEY = /rating|(^|_)buy(_|$)|(^|_)capped|cap_reason|(^|_)(hold|reduce|sell)_count$|gate_warning|(^|_)gate_failures$|(^|_)decision_|(^|_)gate_|primary_gate|eligibility_class|coverage_eligible|(^|_)cap_(enforced|would_apply)|execution_status|portfolio_actionable|(actionable|recommendation)_rank|trend_confirmed/;
export const NOT_A_RATING = /^rs_rating/;

/** Snapshot column, run column or payload key that carries a rating or its gates. */
export function isRatingField(key) {
  const k = String(key).toLowerCase();
  return RATING_KEY.test(k) && !NOT_A_RATING.test(k);
}

// The model's verdict as a number or a position -- the blended score, the rank
// ordered by it, and the weights that rebuild it -- is shown to nobody, admins
// included: a published ranking is research under SEBI's rules whatever its
// label. Each viewer builds their own score instead (lib/custom-score.mjs).
// Hidden here, on the server; the database views do not null these yet
// (rating_access_schema.sql).
// Factor scores and percentiles (quality_score, momentum_percentile, ...) stay:
// each describes the stock on one measure, not the model's overall view.
/** Whether an admin sees the verdict. Off: no viewer is shown a ranking until the service is registered. */
export const SHOW_VERDICT = false;

export const VERDICT_KEY =
  /^(prev_)?(investment_rank|score_rank|action_rank|final_score|decision_score(_ceiling)?|evidence_score|research_score(_raw)?|combined_score|score_after_dcf|fundamental_score|technical_score|action_score|timing_score)$|^(rank|score)_change$|_weight$/;

/** Column or payload key that carries the model's overall score, rank or a blend weight. */
export function isVerdictField(key) {
  return VERDICT_KEY.test(String(key).toLowerCase());
}

/** Hidden from a non-admin: a rating field or a verdict field (the latter from an admin too). */
export function isAdminOnlyField(key) {
  return isRatingField(key) || isVerdictField(key);
}

/** Screener query keys that filter on a rating or the score, so filtering cannot reveal either. */
export const RATING_FILTER_KEYS = ["rating", "buyEligible", "excludeCapped", "minScore"];

/** True when a query string sorts by the model's verdict or filters on its score: no viewer's. */
export function usesVerdict(query) {
  const params = new URLSearchParams(query);
  return params.has("minScore") || isVerdictField(params.get("sort") ?? "");
}

/** True when a preset's query string filters on a rating. */
export function usesRatingFilter(query) {
  const params = new URLSearchParams(query);
  return RATING_FILTER_KEYS.some((key) => params.has(key));
}

/** A copy of `row` with every field `hide` names nulled, its `payload`'s dropped. */
function redact(row, hide) {
  if (!row || typeof row !== "object") return row;
  const out = {};
  for (const [key, value] of Object.entries(row)) {
    if (hide(key)) out[key] = null;
    else if (key === "payload" && value && typeof value === "object") {
      out[key] = Object.fromEntries(Object.entries(value).filter(([field]) => !hide(field)));
    } else out[key] = value;
  }
  return out;
}

/**
 * A copy of `row` for a non-admin: ratings and the verdict nulled, its
 * `payload` included. Nulled rather than deleted, so the row keeps the shape
 * its type promises.
 */
export function withoutRatings(row) {
  return redact(row, isAdminOnlyField);
}

/** A copy of `row` for an admin: the verdict nulled, the ratings kept. */
export function withoutVerdict(row) {
  return redact(row, isVerdictField);
}

const RATING_WORD = /\b(STRONG BUY|BUY|HOLD|REDUCE|SELL)\b/;

/**
 * Copy for a viewer: an admin's text as written; anyone else's without the
 * sentences that name a rating or the boundaries that turn a score into one
 * ("BUY needs 40", "Ticks mark the REDUCE / HOLD / BUY boundaries").
 */
export function publicText(admin, text) {
  if (admin || !text) return text;
  return text
    .split(/(?<=\.)\s+/)
    .filter((sentence) => !RATING_WORD.test(sentence))
    .join(" ");
}

/** The Published score card's info text, as written for an admin. */
export const PUBLISHED_SCORE_INFO =
  "The research evidence on a 0-100 scale. Ticks on the ring mark the REDUCE / HOLD / BUY / STRONG BUY boundaries; policy gates limit the rating, not the score.";
