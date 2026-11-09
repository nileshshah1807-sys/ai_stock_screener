import assert from "node:assert/strict";
import test from "node:test";

import { monthlyMovers, pctChange, profitMovers, pulseBases } from "./home-market.mjs";

test("a change needs a positive base", () => {
  assert.ok(Math.abs(pctChange(100, 110) - 10) < 1e-9);
  assert.equal(pctChange(0, 5), null);
  assert.equal(pctChange(null, 5), null);
});

test("bases are the last bar, the one before, and a week and a month back", () => {
  const points = [
    { time: "2026-10-05", value: 80 },
    { time: "2026-10-08", value: 90 },
    { time: "2026-10-30", value: 100 },
    { time: "2026-11-02", value: 101 },
    { time: "2026-11-05", value: 102 },
    { time: "2026-11-06", value: 103 },
  ];
  const bases = pulseBases(points);
  assert.equal(bases.last.value, 103);
  assert.equal(bases.prev, 102);
  assert.equal(bases.week, 100); // 30 Oct, the last bar on or before 30 Oct
  assert.equal(bases.month, 80); // 6 Oct is a gap: the 5 Oct close stands
  assert.equal(pulseBases([]), null);
  assert.equal(pulseBases([{ time: "2026-11-06", value: 1 }]).month, null);
});

test("profit movers skip a loss for a base and rank by rate", () => {
  const card = (symbol, yoy) => ({ symbol, bases: [{ rows: [{ key: "net_profit", yoy }] }] });
  const { rises, falls } = profitMovers(
    [card("A", 40), card("B", -30), card("C", null), card("D", 90), card("E", -80), { symbol: "F", bases: [] }],
    2,
  );
  assert.deepEqual(rises.map((row) => row.symbol), ["D", "A"]);
  assert.deepEqual(falls.map((row) => row.symbol), ["E", "B"]);
});

test("monthly movers are ranked within each index", () => {
  const rows = [
    { symbol: "A", pct_change_1m: 5 },
    { symbol: "B", pct_change_1m: -7 },
    { symbol: "C", pct_change_1m: 12 },
    { symbol: "D", pct_change_1m: null },
    { symbol: "X", pct_change_1m: 99 },
  ];
  const out = monthlyMovers(new Map([["Nifty 50", ["A", "B", "C", "D"]]]), rows, 1);
  const index = out.get("Nifty 50");
  assert.deepEqual(index.gainers.map((row) => row.symbol), ["C"]);
  assert.deepEqual(index.losers.map((row) => row.symbol), ["B"]);
});

test("a shared read is served from memory inside its window, and a rejected result is retried", async () => {
  const { sharedMemo } = await import("./shared-memo.mjs");
  const memo = sharedMemo(1000);
  let reads = 0;
  const load = (value) => async () => (reads++, value);

  assert.equal(await memo("a", load(1), () => true, 0), 1);
  assert.equal(await memo("a", load(2), () => true, 999), 1);
  assert.equal(reads, 1);
  assert.equal(await memo("a", load(3), () => true, 1000), 3);
  assert.equal(await memo("e", load(null), (value) => value !== null, 0), null);
  assert.equal(await memo("e", load(4), (value) => value !== null, 1), 4);
  assert.equal(reads, 4);
});
