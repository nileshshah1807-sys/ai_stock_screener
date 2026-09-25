import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  addPeriod,
  decodeCloses,
  entrySessionAfter,
  equalWeightReturn,
  indexReturns,
  modelForDate,
  needsAdjustedPrice,
  portfolioReturns,
  rebalanceDates,
  rebalanceOption,
  snapRankingDate,
} from "./returns.mjs";

const close = (time, value) => ({ time, close: value });

describe("modelForDate", () => {
  it("labels NSE rankings by the era that produced them", () => {
    assert.equal(modelForDate("NSE", "2026-08-11"), "Model 4.x");
    assert.equal(modelForDate("NSE", "2026-08-13"), "Model 4.x");
    assert.equal(modelForDate("NSE", "2026-08-14"), "Model 5.0");
    assert.equal(modelForDate("NSE", "2026-08-20"), "Model 5.0");
    assert.equal(modelForDate("NSE", "2026-08-21"), "Model 5.1");
    assert.equal(modelForDate("NSE", "2027-01-04"), "Model 5.1");
  });

  it("has a single era for the US", () => {
    assert.equal(modelForDate("US", "2026-09-18"), "Model 5.1");
  });

  it("returns null for an unknown market", () => {
    assert.equal(modelForDate("LSE", "2026-09-18"), null);
  });
});

describe("decodeCloses", () => {
  it("expands deltas into dated closes in major units", () => {
    const row = { session_deltas: "[0,1,2]", closes: "[10000,50,-150]" };
    const sessions = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"];
    assert.deepEqual(decodeCloses(row, sessions), [
      close("2026-09-01", 100),
      close("2026-09-02", 100.5),
      close("2026-09-04", 99),
    ]);
  });

  it("returns nothing for a misaligned or malformed row", () => {
    assert.deepEqual(decodeCloses({ session_deltas: "[0,1]", closes: "[1]" }, ["a", "b"]), []);
    assert.deepEqual(decodeCloses({ session_deltas: "not json", closes: "[1]" }, ["a"]), []);
    assert.deepEqual(decodeCloses(null, ["a"]), []);
  });
});

describe("snapRankingDate", () => {
  const dates = ["2026-08-11", "2026-08-12", "2026-08-14"];

  it("uses the latest ranking on or before the request", () => {
    assert.equal(snapRankingDate(dates, "2026-08-13"), "2026-08-12");
    assert.equal(snapRankingDate(dates, "2026-08-14"), "2026-08-14");
    assert.equal(snapRankingDate(dates, "2026-12-31"), "2026-08-14");
  });

  it("falls back to the first ranking", () => {
    assert.equal(snapRankingDate(dates, "2026-01-01"), "2026-08-11");
    assert.equal(snapRankingDate(dates, undefined), "2026-08-11");
    assert.equal(snapRankingDate(dates, "yesterday"), "2026-08-11");
  });

  it("is null with no rankings", () => {
    assert.equal(snapRankingDate([], "2026-08-11"), null);
  });
});

describe("entrySessionAfter", () => {
  it("is the first session strictly after the ranking", () => {
    const sessions = ["2026-09-18", "2026-09-21", "2026-09-22"];
    assert.equal(entrySessionAfter(sessions, "2026-09-18"), "2026-09-21");
    assert.equal(entrySessionAfter(sessions, "2026-09-19"), "2026-09-21");
    assert.equal(entrySessionAfter(sessions, "2026-09-22"), null);
  });
});

/** Buy-and-hold is a portfolio with a single round. */
function basketReturns(holdings, { entrySession, asOf, costPerSidePct = 0 }) {
  return portfolioReturns(
    [{ entrySession, symbols: holdings.map((holding) => holding.symbol) }],
    new Map(holdings.map((holding) => [holding.symbol, holding.points])),
    { asOf, costPerSidePct },
  );
}

describe("portfolioReturns, buy and hold", () => {
  const options = { entrySession: "2026-09-01", asOf: "2026-09-03" };

  it("averages each holding's move from its entry close", () => {
    const result = basketReturns(
      [
        { symbol: "UP", points: [close("2026-08-31", 50), close("2026-09-01", 100), close("2026-09-03", 120)] },
        { symbol: "DOWN", points: [close("2026-09-01", 100), close("2026-09-02", 90), close("2026-09-03", 80)] },
      ],
      options,
    );
    // The close before entry is ignored: that is the ranking's own session.
    assert.equal(result.stocks[0].entry.close, 100);
    assert.ok(Math.abs(result.grossPct) < 1e-9);
    assert.deepEqual(
      result.curve.map((point) => point.time),
      ["2026-09-01", "2026-09-02", "2026-09-03"],
    );
    // UP did not trade on 09-02, so it is carried at its 09-01 close.
    assert.ok(Math.abs(result.curve[1].value - -5) < 1e-9);
  });

  it("keeps a holding in cash until its first close, and flags the delay", () => {
    const result = basketReturns(
      [
        { symbol: "THIN", points: [close("2026-09-02", 10), close("2026-09-03", 11)] },
        { symbol: "FLAT", points: [close("2026-09-01", 50), close("2026-09-03", 50)] },
      ],
      options,
    );
    assert.ok(Math.abs(result.curve[0].value) < 1e-9);
    assert.equal(result.stocks[0].delayedEntry, true);
    assert.equal(result.stocks[1].delayedEntry, false);
    assert.ok(Math.abs(result.grossPct - 5) < 1e-9);
  });

  it("keeps a holding that never traded as cash rather than dropping it", () => {
    const result = basketReturns(
      [
        { symbol: "GONE", points: [] },
        { symbol: "DOUBLE", points: [close("2026-09-01", 10), close("2026-09-03", 20)] },
      ],
      options,
    );
    assert.equal(result.stocks[0].returnPct, null);
    assert.ok(Math.abs(result.grossPct - 50) < 1e-9);
  });

  it("charges costs on the way in and out", () => {
    const result = basketReturns(
      [{ symbol: "FLAT", points: [close("2026-09-01", 100), close("2026-09-03", 100)] }],
      { ...options, costPerSidePct: 0.3 },
    );
    assert.ok(Math.abs(result.grossPct) < 1e-9);
    // The gross curve rides along, so the page can drop costs without a request.
    assert.ok(Math.abs(result.grossCurve.at(-1).value - result.grossPct) < 1e-9);
    assert.ok(Math.abs(result.netPct - ((0.997 ** 2 - 1) * 100)) < 1e-9);
    assert.ok(Math.abs(result.curve.at(-1).value - result.netPct) < 1e-9);
  });

  it("ignores closes after the as-of date", () => {
    const result = basketReturns(
      [{ symbol: "A", points: [close("2026-09-01", 100), close("2026-09-03", 110), close("2026-09-04", 500)] }],
      options,
    );
    assert.ok(Math.abs(result.grossPct - 10) < 1e-9);
  });

  it("is empty without holdings or a window", () => {
    assert.deepEqual(basketReturns([], options).curve, []);
    assert.equal(
      basketReturns([{ symbol: "A", points: [] }], { entrySession: "2026-09-03", asOf: "2026-09-01" }).grossPct,
      null,
    );
  });
});

describe("portfolioReturns, rebalanced", () => {
  const closes = new Map([
    ["A", [close("2026-09-01", 100), close("2026-09-08", 110), close("2026-09-15", 121)]],
    ["B", [close("2026-09-01", 100), close("2026-09-08", 90), close("2026-09-15", 45)]],
    ["C", [close("2026-09-01", 50), close("2026-09-08", 50), close("2026-09-15", 60)]],
  ]);
  const rounds = [
    { entrySession: "2026-09-01", symbols: ["A", "B"] },
    { entrySession: "2026-09-08", symbols: ["A", "C"] },
  ];

  it("sells what dropped out, buys what came in, and resets to equal weight", () => {
    const result = portfolioReturns(rounds, closes, { asOf: "2026-09-15" });
    // 09-08: A 0.55 + B 0.45 = 1.00, reset to A 0.50 + C 0.50.
    // 09-15: A 0.50 x 1.10 + C 0.50 x 1.20 = 1.15. B's later halving is avoided.
    assert.ok(Math.abs(result.grossPct - 15) < 1e-9);
    assert.deepEqual(result.trades[1].bought, ["C"]);
    assert.deepEqual(result.trades[1].sold, ["B"]);
    assert.deepEqual(result.stocks.map((stock) => stock.symbol), ["A", "C"]);
    // A has been held since the first round; C since the second.
    assert.equal(result.stocks[0].heldSince, "2026-09-01");
    assert.equal(result.stocks[1].heldSince, "2026-09-08");
    assert.ok(Math.abs(result.stocks[0].returnPct - 21) < 1e-9);
  });

  it("charges costs only on the value traded", () => {
    const result = portfolioReturns(rounds, closes, { asOf: "2026-09-15", costPerSidePct: 1 });
    // Round 1 buys 1.00 of stock: cost 0.01. Round 2 trims A 0.5445 -> 0.49005,
    // sells B 0.4455 and buys C 0.49005: 0.99 of value traded, cost 0.0099.
    assert.ok(Math.abs(result.trades[0].costPct - 1) < 1e-9);
    assert.ok(Math.abs(result.trades[1].costPct - 1) < 1e-9);
    const expected = (0.99 - 0.0099) / 2 * (1.1 + 1.2) * 0.99;
    assert.ok(Math.abs(result.netPct - (expected - 1) * 100) < 1e-9);
  });

  it("an unchanged basket only pays to restore equal weight", () => {
    const same = [
      { entrySession: "2026-09-01", symbols: ["A", "C"] },
      { entrySession: "2026-09-08", symbols: ["A", "C"] },
    ];
    const result = portfolioReturns(same, closes, { asOf: "2026-09-15", costPerSidePct: 1 });
    assert.deepEqual(result.trades[1].bought, []);
    assert.deepEqual(result.trades[1].sold, []);
    // A grew to 0.5445 and C stayed 0.495: 0.02475 moves each way.
    assert.ok(result.trades[1].costPct > 0 && result.trades[1].costPct < 0.1);
  });
});

describe("rebalance schedule", () => {
  const dates = ["2026-08-11", "2026-08-12", "2026-08-18", "2026-08-19", "2026-08-25", "2026-09-11", "2026-09-14"];

  it("never rebalances by default", () => {
    assert.deepEqual(rebalanceDates(dates, "2026-08-11", rebalanceOption("never")), ["2026-08-11"]);
    assert.equal(rebalanceOption("bogus").value, "never");
  });

  it("takes the first ranking on or after each boundary", () => {
    assert.deepEqual(
      rebalanceDates(dates, "2026-08-11", rebalanceOption("1w")),
      ["2026-08-11", "2026-08-18", "2026-08-25", "2026-09-11"],
    );
  });

  it("measures the next boundary from the ranking actually used", () => {
    // 1M from 08-11 is 09-11; from there the next boundary is 10-11.
    assert.deepEqual(
      rebalanceDates(dates, "2026-08-11", rebalanceOption("1m")),
      ["2026-08-11", "2026-09-11"],
    );
  });

  it("clamps a month step to the month's last day", () => {
    assert.equal(addPeriod("2026-01-31", { months: 1 }), "2026-02-28");
    assert.equal(addPeriod("2026-08-24", { days: 14 }), "2026-09-07");
    assert.equal(addPeriod("2026-08-24", { months: 3 }), "2026-11-24");
  });
});

describe("indexReturns", () => {
  it("measures from the first level on or after entry", () => {
    const points = [
      { time: "2026-08-31", value: 90 },
      { time: "2026-09-01", value: 100 },
      { time: "2026-09-02", value: 105 },
      { time: "2026-09-04", value: 200 },
    ];
    const result = indexReturns(points, { entrySession: "2026-09-01", asOf: "2026-09-03" });
    assert.ok(Math.abs(result.returnPct - 5) < 1e-9);
    assert.equal(result.through, "2026-09-02");
    assert.equal(result.curve[0].value, 0);
  });

  it("is null when the index has nothing in the window", () => {
    assert.equal(indexReturns([], { entrySession: "2026-09-01", asOf: "2026-09-03" }).returnPct, null);
  });
});

describe("needsAdjustedPrice", () => {
  it("accepts an ordinary move", () => {
    assert.equal(needsAdjustedPrice(100, 112), false);
    assert.equal(needsAdjustedPrice(100, 75), false);
  });

  it("re-reads a split-sized jump or a missing price", () => {
    assert.equal(needsAdjustedPrice(100, 50), true);
    assert.equal(needsAdjustedPrice(100, 200), true);
    assert.equal(needsAdjustedPrice(null, 100), true);
    assert.equal(needsAdjustedPrice(100, 0), true);
  });
});

describe("equalWeightReturn", () => {
  it("averages ratios and skips unusable pairs", () => {
    const value = equalWeightReturn([
      { entry: 100, last: 110 },
      { entry: 50, last: 45 },
      { entry: 0, last: 10 },
    ]);
    assert.ok(Math.abs(value - 0) < 1e-9);
  });

  it("is null with nothing usable", () => {
    assert.equal(equalWeightReturn([]), null);
  });
});
