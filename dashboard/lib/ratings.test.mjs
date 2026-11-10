import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  NOT_A_RATING,
  RATING_KEY,
  PUBLISHED_SCORE_INFO,
  isRatingField,
  publicText,
  usesRatingFilter,
  withoutRatings,
} from "./ratings.mjs";

test("the database redacts exactly the fields the dashboard does", () => {
  const sql = readFileSync(
    new URL("../../storage/rating_access_schema.sql", import.meta.url),
    "utf8",
  );
  assert.ok(sql.includes(`~ '${RATING_KEY.source}'`), "is_rating_field matches RATING_KEY");
  assert.ok(sql.includes(`!~ '${NOT_A_RATING.source}'`), "is_rating_field matches NOT_A_RATING");
});

test("rating columns, gates and counts are rating fields", () => {
  for (const key of [
    "rating",
    "policy_eligible_rating",
    "research_rating",
    "prev_rating",
    "buy_eligible",
    "strong_buy_eligible",
    "rating_capped",
    "rating_cap_reason",
    "decision_cap_reason",
    "strong_buy_count",
    "buy_count",
    "hold_count",
    "reduce_count",
    "sell_count",
    "Rating",
    "Buy_Gate_Reason",
    "Strong_Buy_Score_Margin",
    "Transcript_Strong_Buy_Capped",
    // Free text that spells the rating out ("would cap this at HOLD", "STRONG BUY floor").
    "Gate_Warning",
    "Gate_Failures",
    // Columns the rating can be read back from (Rating = rating_from_score(Decision_Score)).
    "decision_score",
    "decision_score_ceiling",
    "decision_cap_applied",
    "decision_stability_status",
    "eligibility_class",
    "primary_gate",
    "gate_severity",
    "gate_failure_count",
    "gate_borderline",
    "Gate_Borderline_Reasons",
    "Cap_Enforced",
    "execution_status",
    "portfolio_actionable",
    "actionable_rank",
    "recommendation_rank",
    "trend_confirmed",
    "coverage_eligible",
    "Fundamental_Coverage_Eligible",
  ]) {
    assert.ok(isRatingField(key), key);
  }
});

test("relative strength and the evidence are not rating fields", () => {
  for (const key of [
    "rs_rating",
    "RS_Rating_Change_1M",
    "final_score",
    "investment_rank",
    "stage",
    "row_count",
    "evidence_score",
    "research_score",
    "score_rank",
    "action_rank",
    "action_score",
    "entry_state",
    "market_regime",
    "value_quality_cap_applied",
    "is_sme",
    "unrated_reason",
    // A score with its ceiling left off, not a rating ceiling.
    "value_score_uncapped",
  ]) {
    assert.ok(!isRatingField(key), key);
  }
});

test("withoutRatings nulls columns and drops payload keys", () => {
  const row = {
    symbol: "TCS",
    rating: "BUY",
    rs_rating: 91,
    payload: { Rating: "BUY", Buy_Eligible: true, RS_Rating: 91, Final_Score: 72 },
  };
  assert.deepEqual(withoutRatings(row), {
    symbol: "TCS",
    rating: null,
    rs_rating: 91,
    payload: { RS_Rating: 91, Final_Score: 72 },
  });
  assert.equal(row.rating, "BUY", "the input is not mutated");
  assert.equal(withoutRatings(null), null);
});

test("a preset filtering on a rating is recognised", () => {
  assert.ok(usesRatingFilter("rating=BUY&actionable=1"));
  assert.ok(usesRatingFilter("minScore=60&excludeCapped=1"));
  assert.ok(!usesRatingFilter("minQuality=70&sort=research_score"));
});

test("publicText leaves an admin's copy alone and drops rating sentences for anyone else", () => {
  assert.equal(publicText(true, PUBLISHED_SCORE_INFO), PUBLISHED_SCORE_INFO);
  const shown = publicText(false, PUBLISHED_SCORE_INFO);
  assert.equal(shown, "The research evidence on a 0-100 scale.");
  assert.doesNotMatch(shown, /REDUCE|HOLD|BUY|SELL|rating/);
  assert.equal(
    publicText(false, "Quality percentile: ROIC, cash generation. BUY needs 40, STRONG BUY 70."),
    "Quality percentile: ROIC, cash generation.",
  );
  assert.equal(publicText(false, null), null);
});

test("publicText drops the market-regime sentence that names a rating", () => {
  const shown = publicText(false, "Index inside the band, or level and trend disagree. STRONG BUY needs exceptional momentum.");
  assert.equal(shown, "Index inside the band, or level and trend disagree.");
});
