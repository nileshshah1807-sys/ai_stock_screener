import assert from "node:assert/strict";
import test from "node:test";

import { buildHolders, buildPattern, QUARTERS_SHOWN } from "./shareholding.mjs";

// ONWARDTEC as filed (StockScans prints the same figures).
function quarter(period_end, promoter, fii, dii, shareholders, holders = []) {
  const publicStake = Math.round((100 - promoter - fii - dii) * 100) / 100;
  return { period_end, promoter, fii, dii, public: publicStake, shareholders, holders };
}

const ONWARD = [
  quarter("2025-09-30", 39.02, 9.21, 4.0, 22267),
  quarter("2025-12-31", 39.09, 9.4, 2.9, 22254),
  quarter("2026-03-31", 39.07, 9.83, 3.53, 20829),
  quarter("2026-06-30", 39.97, 9.32, 1.79, 22336),
  quarter("2026-09-30", 40.2, 9.28, 1.74, 21521),
];

test("the pattern reads latest last, with QoQ and YoY in points", () => {
  const { columns, rows } = buildPattern([...ONWARD].reverse());
  assert.deepEqual(columns.map((c) => c.label), ["Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"]);
  const promoter = rows.find((row) => row.key === "promoter");
  assert.deepEqual(promoter.cells, [39.02, 39.09, 39.07, 39.97, 40.2]);
  assert.equal(promoter.qoq, 0.23);
  assert.equal(promoter.yoy, 1.18);
  assert.equal(rows.find((row) => row.key === "public").cells.at(-1), 48.78);
  assert.equal(rows.find((row) => row.key === "shareholders").qoq, -815);
});

test("a falling public stake or shareholder count is the good direction", () => {
  const { rows } = buildPattern(ONWARD);
  const better = rows.filter((row) => row.lowerIsBetter).map((row) => row.key);
  assert.deepEqual(better, ["public", "shareholders"]);
});

test("a missing quarter leaves QoQ blank rather than comparing the wrong one", () => {
  const { rows } = buildPattern(ONWARD.filter((row) => row.period_end !== "2026-06-30"));
  const promoter = rows.find((row) => row.key === "promoter");
  assert.equal(promoter.qoq, null);
  assert.equal(promoter.yoy, 1.18);
});

test("only the last ten quarters are shown", () => {
  const many = Array.from({ length: 14 }, (_, i) => {
    const year = 2023 + Math.floor(i / 4);
    const end = ["03-31", "06-30", "09-30", "12-31"][i % 4];
    return quarter(`${year}-${end}`, 40, 10, 5, 100);
  });
  assert.equal(buildPattern(many).columns.length, QUARTERS_SHOWN);
});

test("holders match across quarters by name, whatever the case", () => {
  const patterns = [
    quarter("2026-06-30", 39.97, 9.32, 1.79, 1, [
      { name: "ICICI Prudential Technology Fund", group: "dii", pct: 1.65 },
      { name: "JHM Enterprises Private Limited", group: "promoter", pct: 35.14 },
    ]),
    quarter("2026-09-30", 40.2, 9.28, 1.74, 1, [
      { name: "ICICI PRUDENTIAL  TECHNOLOGY FUND", group: "dii", pct: 1.43 },
      { name: "INFINITY PORTFOLIO HOLDINGS", group: "fii", pct: 8.29 },
      { name: "Jhm Enterprises Private Limited", group: "promoter", pct: 35.39 },
    ]),
  ];
  const { rows } = buildHolders(patterns, ["fii", "dii", "public"]);
  assert.deepEqual(
    rows.map((row) => [row.name, row.cells]),
    [
      ["INFINITY PORTFOLIO HOLDINGS", [null, 8.29]],
      ["ICICI PRUDENTIAL  TECHNOLOGY FUND", [1.65, 1.43]],
    ],
  );
  assert.deepEqual(buildHolders(patterns, ["promoter"]).rows[0].cells, [35.14, 35.39]);
});

test("a promoter-group entity at zero in every quarter is not listed", () => {
  const patterns = [
    quarter("2026-06-30", 71.77, 9, 13, 1, [
      { name: "Tata Sons Private Limited", group: "promoter", pct: 71.74 },
      { name: "Air India Limited", group: "promoter", pct: 0 },
    ]),
  ];
  assert.deepEqual(buildHolders(patterns, ["promoter"]).rows.map((row) => row.name), ["Tata Sons Private Limited"]);
});
