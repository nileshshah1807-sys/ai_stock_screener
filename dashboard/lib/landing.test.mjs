import assert from "node:assert/strict";
import test from "node:test";

import { SAMPLE_MARKETS, STAGE_WORD, STAGES, sampleRows } from "./landing.mjs";

test("the Stage 2 chip keeps only Stage 2 rows", () => {
  for (const market of Object.keys(SAMPLE_MARKETS)) {
    const rows = sampleRows(market, true);
    assert.ok(rows.length > 0 && rows.every((row) => row.stage === 2));
    assert.ok(sampleRows(market, false).length > rows.length);
  }
});

test("an unknown market has no rows rather than throwing", () => {
  assert.deepEqual(sampleRows("xx", false), []);
});

test("every stage has a plain word", () => {
  assert.deepEqual(STAGES.map((st) => STAGE_WORD[st.stage]), STAGES.map((st) => st.name));
});

test("the sieve: gates only lose dots, survivors are ranked 1..n, and the picture is deterministic", async () => {
  const { sieveDots, stageSeries, FACTORS, TONE } = await import("./landing.mjs");
  const dots = sieveDots();
  assert.equal(dots.length, 84);
  assert.equal(sampleRows("ind", false).length, 6);
  const survivors = dots.filter((d) => d.fate === 3);
  assert.equal(survivors.length, 6);
  assert.deepEqual(survivors.map((d) => d.rank).sort((a, b) => a - b), [1, 2, 3, 4, 5, 6]);
  assert.deepEqual(sieveDots(), dots);
  const s = stageSeries();
  assert.equal(s.price.length, 220);
  assert.equal(s.ma200.length, 220);
  assert.ok(s.ma200.every((v) => v !== null));
  assert.equal(s.bands.at(-1).to, 1);
  assert.equal(FACTORS.reduce((t, f) => t + f.weight, 0), 100);
  assert.ok(TONE.cuts.every(([cut], i, a) => !i || cut > a[i - 1][0]) && TONE.median > TONE.cuts[1][0]);
});

test("the evening is drawn to scale and no sampled row sits in a downtrend", async () => {
  const { eveningPosition, EVENING } = await import("./landing.mjs");
  assert.equal(eveningPosition("15:30"), 0);
  assert.equal(eveningPosition("22:00"), 1);
  assert.ok(EVENING.every(([t], i, a) => !i || eveningPosition(t) > eveningPosition(a[i - 1][0])));
  for (const market of Object.keys(SAMPLE_MARKETS)) assert.ok(SAMPLE_MARKETS[market].rows.every((r) => r.stage <= 2));
});
