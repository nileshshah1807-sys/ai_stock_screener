import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  addPeriod,
  decodeCloses,
  compoundIndex,
  entrySessionAfter,
  indexReturns,
  modelForDate,
  pickKey,
  pickOption,
  portfolioReturns,
  selectBaskets,
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
    assert.equal(modelForDate("NSE", "2026-10-07"), "Model 5.1");
    assert.equal(modelForDate("NSE", "2026-10-08"), "Model 5.2");
    assert.equal(modelForDate("NSE", "2027-01-04"), "Model 5.2");
  });

  it("switches the US one run earlier, the same evening", () => {
    assert.equal(modelForDate("US", "2026-09-18"), "Model 5.1");
    assert.equal(modelForDate("US", "2026-10-06"), "Model 5.1");
    assert.equal(modelForDate("US", "2026-10-07"), "Model 5.2");
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

  it("sells what dropped out and buys what came in with the sale money", () => {
    const result = portfolioReturns(rounds, closes, { asOf: "2026-09-15" });
    // 09-08: A 0.55 + B 0.45. B is sold and its 0.45 buys C; A is kept as it
    // is, not trimmed back to half. 09-15: A 0.605 + C 0.54 = 1.145.
    assert.ok(Math.abs(result.grossPct - 14.5) < 1e-9);
    assert.deepEqual(result.trades[1].bought, ["C"]);
    assert.deepEqual(result.trades[1].sold, ["B"]);
    assert.deepEqual(result.stocks.map((stock) => stock.symbol), ["A", "C"]);
    // A has been held since the first round; C since the second.
    assert.equal(result.stocks[0].heldSince, "2026-09-01");
    assert.equal(result.stocks[1].heldSince, "2026-09-08");
    assert.ok(Math.abs(result.stocks[0].returnPct - 21) < 1e-9);
  });

  it("logs each round's own period return", () => {
    const result = portfolioReturns(rounds, closes, { asOf: "2026-09-15" });
    // Round 1 (A, B): 1.00 -> 1.00 by 09-08. Round 2 (A 0.55, C 0.45): 1.00 -> 1.145.
    assert.equal(result.trades[0].periodEnd, "2026-09-08");
    assert.ok(Math.abs(result.trades[0].returnPct) < 1e-9);
    assert.equal(result.trades[1].periodEnd, "2026-09-15");
    assert.ok(Math.abs(result.trades[1].returnPct - 14.5) < 1e-9);
  });

  it("records each sold position from its fill to its sale", () => {
    const result = portfolioReturns(rounds, closes, { asOf: "2026-09-15" });
    // B was bought at 100 on 09-01 and sold at 90 on 09-08; A and C stay open.
    assert.equal(result.closedTrades.length, 1);
    const [trade] = result.closedTrades;
    assert.equal(trade.symbol, "B");
    assert.equal(trade.boughtRound, "2026-09-01");
    assert.deepEqual(trade.entry, close("2026-09-01", 100));
    assert.deepEqual(trade.exit, close("2026-09-08", 90));
    assert.equal(trade.soldOn, "2026-09-08");
    assert.ok(Math.abs(trade.returnPct - -10) < 1e-9);
  });

  it("keeps a round's cost out of its period return", () => {
    const net = portfolioReturns(rounds, closes, { asOf: "2026-09-15", costPerSidePct: 1 });
    // After round 2's trades: A 0.5445 kept, C bought with B's 0.4455 less
    // 1% on the sale and 1% on the purchase.
    const c = 0.4455 * 0.99 * 0.99;
    const expected = ((0.5445 * 1.1 + c * 1.2) / (0.5445 + c) - 1) * 100;
    assert.ok(Math.abs(net.trades[1].returnPct - expected) < 1e-9);
    assert.ok(net.trades[1].costPct > 0);
  });

  it("charges costs only on what is sold and bought", () => {
    const result = portfolioReturns(rounds, closes, { asOf: "2026-09-15", costPerSidePct: 1 });
    // Round 1 buys 1.00 of stock: cost 0.01. Round 2 sells B's 0.4455 and
    // buys C with the rest: 0.004455 + 0.00441045. A is not traded.
    assert.ok(Math.abs(result.trades[0].costPct - 1) < 1e-9);
    assert.ok(Math.abs(result.trades[1].costPct - ((0.004455 + 0.00441045) / 0.99) * 100) < 1e-9);
    const expected = (0.5445 * 1.1 + 0.4455 * 0.99 * 0.99 * 1.2) * 0.99;
    assert.ok(Math.abs(result.netPct - (expected - 1) * 100) < 1e-9);
  });

  it("an unchanged basket trades nothing and matches buy and hold", () => {
    const same = [
      { entrySession: "2026-09-01", symbols: ["A", "C"] },
      { entrySession: "2026-09-08", symbols: ["A", "C"] },
    ];
    const result = portfolioReturns(same, closes, { asOf: "2026-09-15", costPerSidePct: 1 });
    assert.deepEqual(result.trades[1].bought, []);
    assert.deepEqual(result.trades[1].sold, []);
    assert.equal(result.trades[1].costPct, 0);
    const held = portfolioReturns(same.slice(0, 1), closes, { asOf: "2026-09-15", costPerSidePct: 1 });
    assert.ok(Math.abs(result.netPct - held.netPct) < 1e-9);
  });

  it("an empty slot waits in cash until a stock fills it", () => {
    const short = [
      { entrySession: "2026-09-01", symbols: ["A"] },
      { entrySession: "2026-09-08", symbols: ["A", "C"] },
    ];
    const once = portfolioReturns(short.slice(0, 1), closes, { asOf: "2026-09-15", slots: 2 });
    // Half in A, half in cash: 0.5 x 1.21 + 0.5.
    assert.ok(Math.abs(once.grossPct - 10.5) < 1e-9);
    const filled = portfolioReturns(short, closes, { asOf: "2026-09-15", slots: 2 });
    // The cash half buys C on 09-08 and rises 20%: 0.605 + 0.6.
    assert.ok(Math.abs(filled.grossPct - 20.5) < 1e-9);
  });

  it("a round with no names sells to cash until names return", () => {
    const empty = [
      { entrySession: "2026-09-01", symbols: ["A"] },
      { entrySession: "2026-09-08", symbols: [] },
    ];
    const result = portfolioReturns(empty, closes, { asOf: "2026-09-15" });
    // A rose 10% to 09-08, then the basket sat in cash while A rose again.
    assert.ok(Math.abs(result.grossPct - 10) < 1e-9);
    assert.deepEqual(result.trades[1].sold, ["A"]);
    assert.deepEqual(result.stocks, []);
    assert.ok(Math.abs(result.trades[1].returnPct) < 1e-9);
  });
});

describe("portfolioReturns, booked and open gains", () => {
  const closes = new Map([
    ["A", [close("2026-09-01", 100), close("2026-09-08", 110), close("2026-09-15", 121)]],
    ["B", [close("2026-09-01", 100), close("2026-09-08", 90), close("2026-09-15", 45)]],
    ["C", [close("2026-09-01", 50), close("2026-09-08", 50), close("2026-09-15", 60)]],
  ]);
  const rounds = [
    { entrySession: "2026-09-01", symbols: ["A", "B"] },
    { entrySession: "2026-09-08", symbols: ["A", "C"] },
  ];
  const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} != ${expected}`);

  it("splits the return into gains booked on sales and gains still open", () => {
    const result = portfolioReturns(rounds, closes, { asOf: "2026-09-15" });
    // B sold at 0.45 on a 0.50 cost books -0.05. A is 0.605 on 0.50 and C
    // 0.54 on 0.45, so 0.105 + 0.09 is open.
    near(result.grossPnl.bookedPct, -5);
    near(result.grossPnl.openPct, 19.5);
    near(result.grossPnl.costsPct, 0);
    near(result.grossPnl.bookedPct + result.grossPnl.openPct, result.grossPct);
  });

  it("adds up to the net return once costs are taken out", () => {
    const result = portfolioReturns(rounds, closes, { asOf: "2026-09-15", costPerSidePct: 1 });
    const { bookedPct, openPct, costsPct, paidPct } = result.pnl;
    near(bookedPct + openPct - costsPct, result.netPct);
    // Paid on the first purchase, B's sale and C's purchase; the rest is
    // selling everything today.
    near(paidPct, (0.01 + 0.004455 + 0.00441045) * 100);
    assert.ok(costsPct > paidPct);
  });

  it("gives each holding and each closed position its share", () => {
    for (const costPerSidePct of [0, 1]) {
      const result = portfolioReturns(rounds, closes, { asOf: "2026-09-15", costPerSidePct });
      const pnl = costPerSidePct ? result.pnl : result.grossPnl;
      const open = result.stocks.reduce(
        (sum, stock) => sum + (costPerSidePct ? stock.openPts : stock.grossOpenPts),
        0,
      );
      near(open, pnl.openPct);
    }
    const [sold] = portfolioReturns(rounds, closes, { asOf: "2026-09-15" }).closedTrades;
    near(sold.grossBookedPts, -5);
  });

  it("books nothing while a round sits in cash", () => {
    const empty = [
      { entrySession: "2026-09-01", symbols: ["A"] },
      { entrySession: "2026-09-08", symbols: [] },
    ];
    const result = portfolioReturns(empty, closes, { asOf: "2026-09-15" });
    near(result.grossPnl.bookedPct, 10);
    near(result.grossPnl.openPct, 0);
  });
});

describe("portfolioReturns, trailing stop", () => {
  const closes = new Map([
    ["A", [close("2026-09-01", 100), close("2026-09-02", 120), close("2026-09-03", 95), close("2026-09-04", 90), close("2026-09-07", 200)]],
    ["B", [close("2026-09-01", 100), close("2026-09-02", 100), close("2026-09-03", 100), close("2026-09-04", 100), close("2026-09-07", 100)]],
  ]);
  const rounds = [{ entrySession: "2026-09-01", symbols: ["A", "B"] }];

  it("sells at the close after a holding closes the stop below its high", () => {
    const result = portfolioReturns(rounds, closes, { asOf: "2026-09-07", trailingStopPct: 20 });
    // A peaks at 120 on 09-02; 95 on 09-03 is more than 20% below, so it is
    // sold at 09-04's close of 90 and misses the jump to 200.
    assert.deepEqual(result.stops, [{ symbol: "A", signalled: "2026-09-03", soldOn: "2026-09-04" }]);
    assert.ok(Math.abs(result.grossPct - (0.5 * 0.9 + 0.5 - 1) * 100) < 1e-9);
    assert.equal(result.closedTrades[0].symbol, "A");
    assert.deepEqual(result.closedTrades[0].exit, close("2026-09-04", 90));
    assert.equal(result.closedTrades[0].stopped, true);
  });

  it("does nothing when off", () => {
    const result = portfolioReturns(rounds, closes, { asOf: "2026-09-07" });
    assert.deepEqual(result.stops, []);
    assert.ok(Math.abs(result.grossPct - 50) < 1e-9);
  });
});

describe("portfolioReturns, part of the money kept as cash", () => {
  const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} != ${expected}`);
  const closes = new Map([
    ["A", [close("2026-09-01", 100), close("2026-09-08", 200), close("2026-09-15", 100)]],
  ]);

  it("keeps the rest out of the basket, earning nothing", () => {
    const rounds = [{ entrySession: "2026-09-01", symbols: ["A"] }];
    const result = portfolioReturns(rounds, closes, { asOf: "2026-09-08", investedPct: 60 });
    // 0.6 in A doubles to 1.2; the 0.4 of cash stays 0.4.
    near(result.grossPct, (1.2 + 0.4 - 1) * 100);
  });

  it("restores the split at each rebalance by resizing the basket", () => {
    const rounds = [
      { entrySession: "2026-09-01", symbols: ["A"] },
      { entrySession: "2026-09-08", symbols: ["A"] },
    ];
    const result = portfolioReturns(rounds, closes, { asOf: "2026-09-15", investedPct: 50 });
    // 09-08: A 1.0 and cash 0.5 -> resized to 0.75 each, booking half of A's
    // 0.5 gain on the quarter sold. 09-15: A halves to 0.375; total 1.125.
    near(result.grossPct, 12.5);
    near(result.grossPnl.bookedPct, 12.5);
    near(result.grossPnl.openPct, 0);
  });

  it("still adds up once costs are in", () => {
    const rounds = [
      { entrySession: "2026-09-01", symbols: ["A"] },
      { entrySession: "2026-09-08", symbols: ["A"] },
    ];
    const result = portfolioReturns(rounds, closes, { asOf: "2026-09-15", investedPct: 70, costPerSidePct: 0.3 });
    const { bookedPct, openPct, costsPct } = result.pnl;
    near(bookedPct + openPct - costsPct, result.netPct);
  });

  it("changes nothing at 100%", () => {
    const rounds = [{ entrySession: "2026-09-01", symbols: ["A"] }];
    const plain = portfolioReturns(rounds, closes, { asOf: "2026-09-15" });
    const full = portfolioReturns(rounds, closes, { asOf: "2026-09-15", investedPct: 100 });
    assert.deepEqual(full.curve, plain.curve);
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

describe("compoundIndex", () => {
  const rows = [
    { observed_on: "2026-08-12", ew_return_pct: 5 },
    { observed_on: "2026-08-13", ew_return_pct: 10 },
    { observed_on: "2026-08-14", ew_return_pct: -10 },
    { observed_on: "2026-08-17", ew_return_pct: 50 },
  ];

  it("compounds the sessions after entry, through the as-of date", () => {
    const result = compoundIndex(rows, { entrySession: "2026-08-12", asOf: "2026-08-14" });
    assert.ok(Math.abs(result.returnPct - (1.1 * 0.9 - 1) * 100) < 1e-9);
    assert.equal(result.through, "2026-08-14");
    assert.equal(result.sessions, 2);
  });

  it("reports where a lagging index stops", () => {
    const result = compoundIndex(rows.slice(0, 2), { entrySession: "2026-08-12", asOf: "2026-08-17" });
    assert.equal(result.through, "2026-08-13");
  });

  it("is null with no indexed session in the window", () => {
    assert.equal(compoundIndex([], { entrySession: "2026-08-12", asOf: "2026-08-14" }).returnPct, null);
  });
});

describe("modelForDate, backtest", () => {
  it("labels every backtest ranking as the fitted model", () => {
    assert.equal(modelForDate("NSE", "2019-03-01", true), "Model 5.2 backtest");
  });
});

describe("pickOption", () => {
  it("falls back to the whole ranking", () => {
    assert.equal(pickOption(undefined).value, "all");
    assert.equal(pickOption("nonsense").value, "all");
  });

  it("names the stored column for each filtered pick", () => {
    assert.deepEqual(pickOption("strong_buy").columns, ["rank_strong_buy"]);
    assert.deepEqual(pickOption("buy").ratings, ["BUY", "STRONG BUY"]);
    assert.equal(pickOption("fresh_stage2").maxAdvanceAge, 30);
  });

  it("combines a rating filter with a stage filter", () => {
    const pick = pickOption("strong_buy+fresh_stage2");
    assert.equal(pick.value, "strong_buy+fresh_stage2");
    assert.deepEqual(pick.ratings, ["STRONG BUY"]);
    assert.equal(pick.stage, "Stage 2");
    assert.equal(pick.maxAdvanceAge, 30);
    assert.deepEqual(pick.columns, ["rank_strong_buy", "rank_fresh_stage2"]);
    assert.equal(pick.phrase, "STRONG BUY, fresh Stage 2");
    // Order in the key does not matter; an unknown part is dropped.
    assert.equal(pickOption("fresh_stage2+buy").value, "buy+fresh_stage2");
    assert.equal(pickOption("buy+nonsense").value, "buy");
  });

  it("builds the key from the two filters", () => {
    assert.equal(pickKey("all", "all"), "all");
    assert.equal(pickKey(null, "stage2"), "stage2");
    assert.equal(pickKey("buy", "fresh_stage2"), "buy+fresh_stage2");
  });
});

describe("selectBaskets", () => {
  it("without a hold rule, each round is its buy list's top N", () => {
    const baskets = selectBaskets(
      [
        { candidates: ["A", "B", "C"], keep: null },
        { candidates: ["C", "D", "A"], keep: null },
      ],
      2,
    );
    assert.deepEqual(baskets, [["A", "B"], ["C", "D"]]);
  });

  it("keeps holdings that pass the hold rule and fills free slots in rank order", () => {
    const baskets = selectBaskets(
      [
        // Bought fresh: A and B.
        { candidates: ["A", "B", "C"], keep: new Set() },
        // A and B are no longer fresh, so off the buy list -- but A is still
        // advancing and stays; B broke down and goes. D fills B's slot.
        { candidates: ["D", "E"], keep: new Set(["A", "C", "D"]) },
        // A now breaks too; the basket refills from the new list.
        { candidates: ["E", "F", "D"], keep: new Set(["D", "E"]) },
      ],
      2,
    );
    assert.deepEqual(baskets, [["A", "B"], ["A", "D"], ["D", "E"]]);
  });

  it("holds fewer than N when too few names pass, and nothing when none do", () => {
    const baskets = selectBaskets(
      [
        { candidates: ["A"], keep: new Set() },
        { candidates: [], keep: new Set() },
      ],
      3,
    );
    assert.deepEqual(baskets, [["A"], []]);
  });
});

describe("pick hold rules", () => {
  it("stage picks hold while advancing, rating picks while BUY or better", () => {
    assert.deepEqual(pickOption("fresh_stage2").holds, ["advancing"]);
    assert.deepEqual(pickOption("stage2").holds, ["advancing"]);
    assert.deepEqual(pickOption("strong_buy").holds, ["buy_plus"]);
    assert.deepEqual(pickOption("all").holds, []);
  });

  it("a combined pick holds only while both rules pass", () => {
    assert.deepEqual(pickOption("buy+stage2").holds, ["buy_plus", "advancing"]);
  });
});
