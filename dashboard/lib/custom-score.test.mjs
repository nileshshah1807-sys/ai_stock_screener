import assert from "node:assert/strict";
import test from "node:test";

import { rawScores, topByMix, NUDGE, nudgeStep, driversText, scoreDrivers, EQUAL_START, IMPORTANCE, POINT_FACTORS, RUN_COLUMNS, SCORE_FACTORS, aheadOf, blockFactor, concallRecency, formatWeights, importanceStep, importanceText, mixShares, parseWeights, rankScores, scoreRun, weightedScore } from "./custom-score.mjs";
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
  // A: percentile 100 + 0.10 * 20; B: ineligible, stays 0.
  const dcf = rawScores(rows, { q: 100, d: 10 });
  assert.equal(dcf.get("A"), 102);
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
  const scores = rawScores(called, { q: 100, c: 100 }, outlooks);
  // Every blend ties at percentile 50; median outlook 60, so 80 is +0.85 * 20.
  assert.equal(scores.get("S29"), 50 + 0.85 * 20);
  assert.equal(scores.get("S0"), 50 - 0.85 * 10);
  // Fewer than 30 calls: measured from 50, not a median.
  assert.equal(rawScores(called.slice(0, 2), { q: 100, c: 100 }, outlooks).get("S0"), 50 + 0.15 * 10);
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

test("a market with no calls: call measures neither score nor move a stock", () => {
  // A US run: no tone, no outlook, nothing eligible.
  const rows = [10, 40, 70, 90].map((q, i) => ({ symbol: `S${i}`, quality_score: q, transcript_score: null }));
  const callsOnly = scoreRun(rows, { t: 100, c: 100 });
  assert.deepEqual([...callsOnly.values()], [null, null, null, null], "no evidence is no score, never 100");
  assert.deepEqual(scoreRun(rows, { q: 50, t: 50, c: 100 }), scoreRun(rows, { q: 50 }));
});

test("every measure carries a name, a one-line caption and a 'What is this?' text, and Risk reads as Steadiness", () => {
  for (const factor of [...SCORE_FACTORS, ...POINT_FACTORS]) {
    assert.ok(factor.label && factor.caption && factor.about, factor.key);
    assert.ok(factor.caption.length <= 70, `${factor.key} caption fits one line`);
    assert.ok(factor.about.split(/\s+/).length <= 60, `${factor.key} explainer under 60 words`);
    assert.doesNotMatch(`${factor.label} ${factor.caption} ${factor.about}`, /\b(buy|sell|hold|recommend|best)\b/i, factor.key);
  }
  assert.equal(SCORE_FACTORS.find((f) => f.key === "r").label, "Steadiness");
  assert.equal(blockFactor("risk").label, "Steadiness");
  assert.equal(blockFactor("nope"), null);
});

test("no advice words anywhere the builder speaks: steps, nudges, readouts and its own text", async () => {
  const advice = /\b(buy|sell|hold|recommend(ed|s)?|best|top picks?)\b/i;
  const spoken = [
    ...IMPORTANCE.map((step) => step.label),
    ...NUDGE.map((step) => step.label),
    aheadOf(72),
    importanceText("Momentum", 35, 30),
    driversText(scoreDrivers({ quality_score: 90, momentum_score: 40 }, { q: 50, m: 50 })),
  ];
  for (const text of spoken) assert.doesNotMatch(text, advice, text);
  const { readFileSync } = await import("node:fs");
  for (const file of ["../components/screener/score-builder.tsx", "../components/landing/factor-bar.tsx"]) {
    assert.doesNotMatch(readFileSync(new URL(file, import.meta.url), "utf8"), advice, file);
  }
});

test("importance reads in words; an older value reads as the nearer step", () => {
  assert.deepEqual(IMPORTANCE.map((step) => step.label), ["Ignore", "A little", "Some", "A lot", "Most"]);
  assert.equal(IMPORTANCE[importanceStep(EQUAL_START.q)].label, "Some");
  assert.equal(importanceStep(30), 3);
  assert.equal(importanceStep(15), 1, "a tie goes to the lower step");
  assert.equal(importanceStep(100), 4);
  assert.equal(importanceStep(undefined), 0);
});

test("shares are whole percents of the mix that add to 100", () => {
  const shares = mixShares({ q: 10, g: 10, m: 10, r: 0 }, SCORE_FACTORS);
  assert.deepEqual(shares.map((entry) => entry.key), ["q", "g", "m"]);
  assert.equal(shares.reduce((sum, entry) => sum + entry.share, 0), 100);
  assert.deepEqual(mixShares({ q: 50, m: 50, d: 100 }, SCORE_FACTORS), [{ key: "q", share: 50 }, { key: "m", share: 50 }], "points are not part of the mix");
  assert.deepEqual(mixShares({}, SCORE_FACTORS), []);
});

test("a screen reader hears the step and the share", () => {
  assert.equal(importanceText("Momentum", 35, 30), "Momentum: A lot, 30% of your mix");
  assert.equal(importanceText("Value", 0, 0), "Value: Ignore");
  assert.equal(aheadOf(71.6), "Ahead of 72% of stocks");
  assert.equal(aheadOf(null), null);
});

test("a row's drivers are its weighted measures by their part of the blend", () => {
  const row = { quality_score: 74, momentum_score: 82, growth_score: null, value_score: 10 };
  const drivers = scoreDrivers(row, { q: 20, m: 35, g: 20, v: 0 });
  assert.deepEqual(drivers.map((entry) => entry.key), ["m", "q"], "unweighted and missing measures are left out");
  assert.ok(Math.abs(drivers.reduce((sum, entry) => sum + entry.part, 0) - 1) < 1e-9);
  assert.equal(driversText(drivers), "Mostly Momentum (82) and Quality (74).");
  assert.equal(driversText(scoreDrivers({ quality_score: 60 }, { q: 20 })), "All Quality (60).");
  assert.equal(driversText([]), null);
});

test("a nudge reads Off, Light or Strong; an older multiple reads as the nearer one", () => {
  assert.deepEqual(NUDGE.map((step) => step.label), ["Off", "Light", "Strong"]);
  assert.equal(nudgeStep(0), 0);
  assert.equal(nudgeStep(45), 2);
  assert.equal(nudgeStep(100), 2);
  assert.equal(nudgeStep(10), 0);
});

test("the preview's top 5 is recomputed for every mix: a step moves scores, a different emphasis changes the names", () => {
  // Ten stocks: s0..s4 lead on quality, s5..s9 on momentum.
  const rows = Array.from({ length: 10 }, (_, i) => ({
    symbol: `s${i}`,
    company: `Co ${i}`,
    quality_score: i < 5 ? 90 - i : 40 - i,
    momentum_score: i < 5 ? 40 - i : 90 - i,
    growth_score: 50,
    value_score: 50,
    risk_score: 50,
  }));
  const names = (weights) => topByMix(rows, weights).map((row) => row.symbol);
  const equal = { ...EQUAL_START };
  const oneStep = { ...EQUAL_START, m: 35 };
  assert.equal(topByMix(rows, equal).length, 5);
  assert.notDeepEqual(
    topByMix(rows, equal).map((row) => [row.symbol, row.score]),
    topByMix(rows, oneStep).map((row) => [row.symbol, row.score]),
    "one step on Momentum changes the list",
  );
  assert.deepEqual(names({ q: 50 }), ["s0", "s1", "s2", "s3", "s4"]);
  assert.deepEqual(names({ m: 50 }), ["s5", "s6", "s7", "s8", "s9"]);
  assert.equal(topByMix(rows, equal)[0].company, "Co 0");
  assert.deepEqual(topByMix([], equal), []);
});

test("nudges move a stock along 0-100, never past it, and never tie the top", () => {
  // Twenty stocks; the five best on quality are also the cheapest, so a strong fair-value nudge piles them up past 100 raw.
  const rows = Array.from({ length: 20 }, (_, i) => ({
    symbol: `s${String(i).padStart(2, "0")}`,
    quality_score: 100 - i,
    dcf_valuation_score: i < 5 ? 100 : 50,
    dcf_blend_eligible: true,
  }));
  const raw = rawScores(rows, { q: 100, d: 50 });
  const scores = scoreRun(rows, { q: 100, d: 50 });
  assert.ok([...raw.values()].filter((v) => v > 100).length >= 2, "raw points do pass 100");
  const values = [...scores.values()];
  assert.equal(Math.max(...values), 100);
  assert.equal(Math.min(...values), 0);
  assert.equal(values.filter((v) => v === 100).length, 1, "one stock at the top, not a tie");
  const order = (map) => [...map.entries()].sort((a, b) => b[1] - a[1]).map(([symbol]) => symbol);
  assert.deepEqual(order(scores), order(raw), "the re-rank keeps the order the points gave");
  // No nudge: the blend's percentile, untouched.
  assert.deepEqual(scoreRun(rows, { q: 100 }), rawScores(rows, { q: 100 }));
});
