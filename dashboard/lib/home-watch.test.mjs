import assert from "node:assert/strict";
import test from "node:test";

import { dealsLag, liveReturns, resultGrowth, shareholdingMoves, trendPoints, windowReturns } from "./home-watch.mjs";

const filing = (symbol, period_end, promoter, fii, dii) => ({ symbol, period_end, promoter, fii, dii });

test("shareholdingMoves compares with the previous quarter and ranks by size", () => {
  const moves = shareholdingMoves([
    filing("AAA", "2026-06-30", 50, 10, 5),
    filing("AAA", "2026-09-30", 50.02, 12.5, 5),
    filing("BBB", "2026-06-30", 40, 10, 5),
    filing("BBB", "2026-09-30", 38, 10, 5.5),
    filing("CCC", "2026-09-30", 30, 10, 5), // no prior quarter
    filing("DDD", "2026-06-30", 30, 10, 5),
    filing("DDD", "2026-09-30", 30.05, 10, 5), // rounding
  ]);
  assert.deepEqual(moves.map((m) => m.symbol), ["AAA", "BBB"]);
  assert.equal(moves[0].fii, 2.5);
  assert.equal(moves[1].promoter, -2);
});

test("shareholdingMoves leaves an unreported group null, not zero", () => {
  const [move] = shareholdingMoves([filing("AAA", "2026-06-30", 50, null, 5), filing("AAA", "2026-09-30", 49, 3, 5)]);
  assert.equal(move.fii, null);
  assert.equal(move.promoter, -1);
});

test("dealsLag is null while current and the days once late", () => {
  assert.equal(dealsLag("2026-11-07", "2026-11-09"), null);
  assert.equal(dealsLag("2026-11-02", "2026-11-09"), 7);
  assert.equal(dealsLag(null, "2026-11-09"), null);
});

test("windowReturns measures 5 and 21 sessions back; short history is null", () => {
  const closes = Array.from({ length: 30 }, (_, i) => 100 + i);
  const { week, month, trend } = windowReturns(closes);
  assert.ok(Math.abs(week - (129 / 124 - 1) * 100) < 1e-9);
  assert.ok(Math.abs(month - (129 / 108 - 1) * 100) < 1e-9);
  assert.equal(trend.length, 22);
  assert.equal(windowReturns([100, 101]).month, null);
});

test("liveReturns uses the live price as the latest point", () => {
  assert.ok(Math.abs(liveReturns([100, 100, 100, 100, 100, 100], 110).week - 10) < 1e-9);
});

test("resultGrowth reads revenue and net profit year on year from the first basis", () => {
  const card = { bases: [{ basis: "consolidated", rows: [{ key: "revenue", yoy: 12 }, { key: "net_profit", yoy: null }] }] };
  assert.deepEqual(resultGrowth(card), { basis: "consolidated", revenue: 12, profit: null });
  assert.equal(resultGrowth({ bases: [] }).revenue, null);
});

test("trendPoints spans the box and needs two values", () => {
  assert.equal(trendPoints([1], 10, 10), "");
  assert.equal(trendPoints([1, 3], 10, 10), "0.0,10.0 10.0,0.0");
});
