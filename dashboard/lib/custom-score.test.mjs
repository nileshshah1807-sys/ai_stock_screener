import assert from "node:assert/strict";
import test from "node:test";

import { EQUAL_START, RUN_COLUMNS, concallRecency, formatWeights, parseWeights, rankScores, scoreRun, weightedScore } from "./custom-score.mjs";
import { isAdminOnlyField } from "./ratings.mjs";

test("weights round-trip through the URL form", () => {
  assert.deepEqual(parseWeights("q20.m30.t10"), { q: 20, m: 30, t: 10 });
  assert.equal(formatWeights({ m: 30, q: 20, t: 10, g: 0 }), "q20.m30.t10");
  assert.equal(parseWeights(""), null);
  assert.equal(parseWeights("q0.zz5.bad"), null, "nothing positive, nothing known");
  assert.deepEqual(parseWeights("q500"), { q: 100 }, "a weight is capped at 100");
  assert.equal(formatWeights(parseWeights("q25.c100.d10")), "q25.d10.c100");
});

test("the score is the weighted mean of the measures it has", () => {
  const row = { quality_score: 80, momentum_score: 60 };
  assert.equal(weightedScore(row, { q: 50, m: 50 }), 70);
});

test("a missing measure is shrunk toward 50, never read as zero", () => {
  const row = { quality_score: 90, momentum_score: null };
  // 90 on half the weight: 50 + (90 - 50) * 0.5.
  assert.equal(weightedScore(row, { q: 50, m: 50 }), 70);
  assert.equal(weightedScore({}, { q: 50 }), null);
});

test("ranking puts the highest first and unscored rows last", () => {
  const rows = [
    { symbol: "B", quality_score: 40 },
    { symbol: "A", quality_score: 90 },
    { symbol: "C" },
  ];
  const scores = scoreRun(rows, { q: 100 });
  assert.deepEqual(rankScores(scores, ["B", "A", "C"]).map((r) => r.symbol), ["A", "B", "C"]);
  assert.equal(scores.get("A"), 100, "the blend is ranked across the run");
  assert.equal(scores.get("B"), 0);
});

test("points: valuation from 50, a recent call from the run's median call", () => {
  const rows = [
    { symbol: "A", quality_score: 60, dcf_valuation_score: 70, dcf_blend_eligible: true },
    { symbol: "B", quality_score: 50, dcf_valuation_score: 90, dcf_blend_eligible: false },
  ];
  // A: percentile 100 + 0.10 * 20, clipped at 100; B: ineligible, stays 0.
  const dcf = scoreRun(rows, { q: 100, d: 10 });
  assert.equal(dcf.get("A"), 100);
  assert.equal(dcf.get("B"), 0);

  const called = Array.from({ length: 30 }, (_, i) => ({
    symbol: `S${i}`,
    quality_score: 50,
    transcript_scoring_eligible: true,
    transcript_score: 60,
    transcript_age_days: 0,
  }));
  const outlooks = new Map(called.map((row, i) => [row.symbol, i < 15 ? 50 : 70]));
  outlooks.set("S29", 80);
  const scores = scoreRun(called, { q: 100, c: 100 }, outlooks);
  // Every blend ties at percentile 50; median outlook 60, so 80 is +0.85 * 20.
  assert.equal(scores.get("S29"), 50 + 0.85 * 20);
  assert.equal(scores.get("S0"), 50 - 0.85 * 10);
  // Fewer than 30 calls: measured from 50, not a median.
  assert.equal(scoreRun(called.slice(0, 2), { q: 100, c: 100 }, outlooks).get("S0"), 50 + 0.15 * 10);
});

test("a call halves in weight every 90 days and is gone after 180", () => {
  assert.equal(concallRecency(0), 1);
  assert.ok(Math.abs(concallRecency(90) - 0.5) < 1e-12);
  assert.equal(concallRecency(181), 0);
  assert.equal(concallRecency(null), 0);
});

test("the builder starts equal and reads nothing admin-only", () => {
  assert.deepEqual(Object.values(EQUAL_START).filter((w) => w > 0), [20, 20, 20, 20, 20]);
  for (const column of [...RUN_COLUMNS, "custom_score"]) {
    assert.ok(!isAdminOnlyField(column), column);
  }
});
