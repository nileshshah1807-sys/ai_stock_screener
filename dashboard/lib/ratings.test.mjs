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
  isVerdictField,
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

test("the model's verdict is admin-only; factor scores and percentiles are not", () => {
  for (const key of ["final_score", "Investment_Rank", "prev_investment_rank", "rank_change", "score_change", "research_score", "Research_Score_Raw", "evidence_score", "Momentum_Weight"]) {
    assert.ok(isVerdictField(key), key);
  }
  for (const key of ["quality_score", "momentum_percentile", "rs_rating", "transcript_score", "market_cap", "value_score_uncapped"]) {
    assert.ok(!isVerdictField(key), key);
  }
});

test("withoutRatings nulls columns and drops payload keys", () => {
  const row = {
    symbol: "TCS",
    rating: "BUY",
    rs_rating: 91,
    final_score: 72,
    investment_rank: 4,
    quality_score: 69.4,
    momentum_percentile: 97,
    payload: { Rating: "BUY", Buy_Eligible: true, RS_Rating: 91, Final_Score: 72, Quality_Weight: 0.25, ROE: 0.21 },
  };
  assert.deepEqual(withoutRatings(row), {
    symbol: "TCS",
    rating: null,
    rs_rating: 91,
    final_score: null,
    investment_rank: null,
    quality_score: 69.4,
    momentum_percentile: 97,
    payload: { RS_Rating: 91, ROE: 0.21 },
  });
  assert.equal(row.rating, "BUY", "the input is not mutated");
  assert.equal(withoutRatings(null), null);
});

test("a preset filtering on a rating is recognised", () => {
  assert.ok(usesRatingFilter("rating=BUY&actionable=1"));
  assert.ok(usesRatingFilter("minScore=60&excludeCapped=1"));
  assert.ok(!usesRatingFilter("minQuality=70&sort=research_score"));
  assert.ok(usesRatingFilter("minScore=70&stage=Stage+2"), "the score is admin-only too");
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

test("an admin keeps the rating but not the verdict, and no preset sorts by it", async () => {
  const { SHOW_VERDICT, usesVerdict, withoutVerdict } = await import("./ratings.mjs");
  assert.equal(SHOW_VERDICT, false);
  const row = withoutVerdict({ rating: "BUY", investment_rank: 3, final_score: 71, decision_score: 70, payload: { Final_Score: 71, Rating: "BUY" } });
  assert.equal(row.rating, "BUY");
  assert.equal(row.investment_rank, null);
  assert.equal(row.final_score, null);
  assert.equal(row.decision_score, null);
  assert.deepEqual(row.payload, { Rating: "BUY" });
  // How the score was built and whether its value leg was capped: the verdict, read back (human, 14 Nov 2026).
  const built = withoutVerdict({ research_score_basis: "q+g", value_quality_cap_applied: true, Research_Score_Basis: "q", value_score: 60 });
  assert.deepEqual(built, { research_score_basis: null, value_quality_cap_applied: null, Research_Score_Basis: null, value_score: 60 });
  assert.ok(usesVerdict("sort=research_score&dir=desc"));
  assert.ok(usesVerdict("minScore=60"));
  assert.ok(!usesVerdict("minQuality=70&sort=market_cap"));
});

test("D1's extra column is redacted in both forms, for viewers and admins", async () => {
  const { withoutVerdict } = await import("./ratings.mjs");
  const extra = { investment_rating: "BUY", score_rank: 3, adx_14: 22 };
  for (const form of [extra, JSON.stringify(extra)]) {
    const read = (value) => (typeof value === "string" ? JSON.parse(value) : value);
    const viewer = withoutRatings({ symbol: "TCS", extra: form }).extra;
    assert.equal(typeof viewer, typeof form);
    assert.deepEqual(read(viewer), { adx_14: 22 });
    assert.deepEqual(read(withoutVerdict({ extra: form }).extra), { investment_rating: "BUY", adx_14: 22 });
  }
  assert.equal(withoutRatings({ extra: "{not json" }).extra, null);
});
