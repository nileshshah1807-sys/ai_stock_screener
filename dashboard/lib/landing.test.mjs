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
  const { toneName } = await import("./landing.mjs");
  assert.deepEqual([toneName(40), toneName(45), toneName(TONE.median), toneName(TONE.sample), toneName(80)], ["Bearish", "Cautious", "Neutral", "Optimistic", "Bullish"]);
});

test("the evening is drawn to scale and no sampled row sits in a downtrend", async () => {
  const { eveningPosition, EVENING } = await import("./landing.mjs");
  assert.equal(eveningPosition("15:30"), 0);
  assert.equal(eveningPosition("22:00"), 1);
  assert.ok(EVENING.every(([t], i, a) => !i || eveningPosition(t) > eveningPosition(a[i - 1][0])));
  for (const market of Object.keys(SAMPLE_MARKETS)) assert.ok(SAMPLE_MARKETS[market].rows.every((r) => r.stage <= 2));
});

test("phone labels keep a minimum gap, and the page's factor weights equal the screener's defaults", async () => {
  const { labelShifts, eveningPosition, EVENING, FACTORS } = await import("./landing.mjs");
  const at = EVENING.map(([t]) => eveningPosition(t) * 30);
  const shifts = labelShifts(at, 1.75);
  const placed = at.map((v, i) => v + shifts[i]);
  assert.ok(placed.every((v, i) => !i || v - placed[i - 1] >= 1.75 - 1e-9));
  assert.equal(shifts[0], 0);
  const { readFileSync } = await import("node:fs");
  const runtime = new URL("../../screener/runtime.py", import.meta.url);
  let source;
  try { source = readFileSync(runtime, "utf8"); } catch { return; } // the dashboard checked out alone
  for (const f of FACTORS) {
    const m = source.match(new RegExp(`FACTOR_WEIGHT_${f.key.toUpperCase()} = _env_float\\("FACTOR_WEIGHT_${f.key.toUpperCase()}", ([0-9.]+)\\)`));
    assert.ok(m, `${f.key} weight not found in runtime.py`);
    assert.equal(Math.round(Number(m[1]) * 100), f.weight);
  }
});
