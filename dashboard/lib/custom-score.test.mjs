import assert from "node:assert/strict";
import test from "node:test";

import { EQUAL_START, formatWeights, parseWeights, rankByWeights, weightedScore } from "./custom-score.mjs";
import { isAdminOnlyField } from "./ratings.mjs";

test("weights round-trip through the URL form", () => {
  assert.deepEqual(parseWeights("q20.m30.t10"), { q: 20, m: 30, t: 10 });
  assert.equal(formatWeights({ m: 30, q: 20, t: 10, g: 0 }), "q20.m30.t10");
  assert.equal(parseWeights(""), null);
  assert.equal(parseWeights("q0.zz5.bad"), null, "nothing positive, nothing known");
  assert.deepEqual(parseWeights("q500"), { q: 100 }, "a weight is capped at 100");
});

test("the score is the weighted mean of the measures it has", () => {
  const row = { quality_percentile: 80, momentum_percentile: 60 };
  assert.equal(weightedScore(row, { q: 50, m: 50 }), 70);
});

test("a missing measure is shrunk toward 50, never read as zero", () => {
  const row = { quality_percentile: 90, momentum_percentile: null };
  // 90 on half the weight: 50 + (90 - 50) * 0.5.
  assert.equal(weightedScore(row, { q: 50, m: 50 }), 70);
  assert.equal(weightedScore({}, { q: 50 }), null);
});

test("ranking puts the highest first and unscored rows last", () => {
  const rows = [
    { symbol: "B", quality_percentile: 40 },
    { symbol: "A", quality_percentile: 90 },
    { symbol: "C" },
  ];
  assert.deepEqual(rankByWeights(rows, { q: 100 }).map((r) => r.symbol), ["A", "B", "C"]);
});

test("the builder starts equal and reads nothing admin-only", () => {
  assert.deepEqual(Object.values(EQUAL_START).filter((w) => w > 0), [20, 20, 20, 20, 20]);
  for (const column of ["quality_percentile", "growth_percentile", "momentum_percentile", "value_percentile", "risk_percentile", "rs_rating", "transcript_score", "custom_score"]) {
    assert.ok(!isAdminOnlyField(column), column);
  }
});
