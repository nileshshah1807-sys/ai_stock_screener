// Buy/sell ratings are shown to admins only. A paid reader of an Indian
// screener that publishes ratings is buying research, which needs SEBI
// registration (docs/commercialisation_readiness.md); until then a viewer sees
// the evidence -- scores, ranks, stages -- and not the label drawn from it.
//
// Redacted on the server, so the value never reaches a viewer's browser: a
// hidden badge whose rating is still in the page payload is not hidden.

// RS_Rating is relative strength, not a buy/sell call. The database applies the
// same rule (is_rating_field in storage/rating_access_schema.sql); the test
// fails if the two drift.
export const RATING_KEY = /rating|(^|_)buy(_|$)|(^|_)capped|cap_reason|(^|_)(hold|reduce|sell)_count$|gate_warning|(^|_)gate_failures$/;
export const NOT_A_RATING = /^rs_rating/;

/** Snapshot column, run column or payload key that carries a rating or its gates. */
export function isRatingField(key) {
  const k = String(key).toLowerCase();
  return RATING_KEY.test(k) && !NOT_A_RATING.test(k);
}

/** Screener query keys that filter on a rating, so filtering cannot reveal one. */
export const RATING_FILTER_KEYS = ["rating", "buyEligible", "excludeCapped"];

/** True when a preset's query string filters on a rating. */
export function usesRatingFilter(query) {
  const params = new URLSearchParams(query);
  return RATING_FILTER_KEYS.some((key) => params.has(key));
}

/**
 * A copy of `row` with every rating field nulled, its `payload` included.
 * Nulled rather than deleted, so the row keeps the shape its type promises.
 */
export function withoutRatings(row) {
  if (!row || typeof row !== "object") return row;
  const out = {};
  for (const [key, value] of Object.entries(row)) {
    if (isRatingField(key)) out[key] = null;
    else if (key === "payload" && value && typeof value === "object") {
      out[key] = Object.fromEntries(
        Object.entries(value).filter(([field]) => !isRatingField(field)),
      );
    } else out[key] = value;
  }
  return out;
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
