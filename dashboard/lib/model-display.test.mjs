import assert from "node:assert/strict";
import test from "node:test";

import {
  factorContribution,
  finiteNumber,
  investmentRankExplanation,
  ranksEligibilityFirst,
  publishedFactorWeight,
  researchScoreMode,
} from "./model-display.mjs";

test("factor weights come from the published row, including non-default candidates", () => {
  const payload = { Quality_Weight: 0.42, Momentum_Weight: "0.18" };

  assert.equal(publishedFactorWeight(payload, "Quality_Weight"), 0.42);
  assert.equal(publishedFactorWeight(payload, "Momentum_Weight"), 0.18);
  assert.equal(publishedFactorWeight(payload, "Risk_Weight"), null);
  assert.equal(finiteNumber("not-a-number"), null);
});

test("displayed factor contribution uses the run's normalized weight", () => {
  assert.equal(factorContribution(80, 0.42), 33.6);
  assert.equal(factorContribution(80, null), null);
});

test("research-score copy distinguishes percentile, weighted and unknown bases", () => {
  assert.equal(researchScoreMode("cross_sectional_percentile"), "percentile");
  assert.equal(researchScoreMode("weighted_block_average"), "weighted");
  assert.equal(researchScoreMode(null), "unknown");
});

test("rank explanation follows the model used by the run", () => {
  assert.match(investmentRankExplanation(true, "5.0.0"), /eligibility class first/i);
  assert.match(investmentRankExplanation(false, "4.0.0"), /decision-score-first/i);
});

test("5.1 runs are described as ranking on research merit", () => {
  const text = investmentRankExplanation(true, "5.1.0");
  assert.match(text, /research score alone/i);
  assert.doesNotMatch(text, /eligibility class first/i);
});

test("an older or unreadable policy version keeps the eligibility-first copy", () => {
  // A historical snapshot must keep describing itself correctly, and an
  // unparseable version must not silently claim the new behaviour.
  assert.equal(ranksEligibilityFirst("5.0.0"), true);
  assert.equal(ranksEligibilityFirst("4.0.0-candidate"), true);
  assert.equal(ranksEligibilityFirst(null), true);
  assert.equal(ranksEligibilityFirst("5.1.0"), false);
  assert.equal(ranksEligibilityFirst("6.0.0"), false);
});
