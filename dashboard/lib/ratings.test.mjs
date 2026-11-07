import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  NOT_A_RATING,
  RATING_KEY,
  isRatingField,
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
    "primary_gate",
    "row_count",
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
