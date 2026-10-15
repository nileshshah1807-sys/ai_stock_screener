import assert from "node:assert/strict";
import { test } from "node:test";

import {
  amountDigits,
  basisTable,
  chosenQuarter,
  formatChange,
  groupByAnnouncedDay,
  quarterEnds,
  quarterLabel,
  resultCard,
} from "./results.mjs";

const CRORE = 1e7;

function filing(period, { consolidated = true, ...lines } = {}) {
  return {
    period_end: period,
    is_consolidated: consolidated,
    filed_at: `${period}T12:00:00+00:00`,
    viewer_url: `https://archive.example/${period}.html`,
    document_url: `https://archive.example/${period}.xml`,
    lines,
  };
}

test("the quarters offered end with the last quarter that has ended", () => {
  assert.deepEqual(quarterEnds("2026-10-15", 3), ["2026-09-30", "2026-06-30", "2026-03-31"]);
  assert.deepEqual(quarterEnds("2026-09-30", 2), ["2026-09-30", "2026-06-30"]);
  assert.deepEqual(quarterEnds("2026-09-29", 1), ["2026-06-30"]);
  assert.deepEqual(quarterEnds("2027-01-02", 2), ["2026-12-31", "2026-09-30"]);
});

test("an Indian quarter is also named by its fiscal quarter", () => {
  assert.equal(quarterLabel("2026-09-30", { fiscal: true }), "Sep 2026 · Q2 FY27");
  assert.equal(quarterLabel("2026-03-31", { fiscal: true }), "Mar 2026 · Q4 FY26");
  assert.equal(quarterLabel("2025-12-31", { fiscal: true }), "Dec 2025 · Q3 FY26");
  assert.equal(quarterLabel("2026-06-30"), "Jun 2026");
});

test("only a quarter the picker offers is taken from the URL", () => {
  const offered = ["2026-09-30", "2026-06-30"];
  assert.equal(chosenQuarter("2026-06-30", offered), "2026-06-30");
  assert.equal(chosenQuarter(["2026-06-30"], offered), "2026-06-30");
  assert.equal(chosenQuarter("2024-06-30", offered), null);
  assert.equal(chosenQuarter(undefined, offered), null);
});

test("a card compares the quarter with the one before and the year-ago quarter", () => {
  const filings = [
    filing("2026-09-30", { revenue: 719 * CRORE, operating_profit: 193 * CRORE, net_profit: 131 * CRORE, eps: 3.6 }),
    filing("2026-06-30", { revenue: 670 * CRORE, operating_profit: 167 * CRORE, net_profit: 114 * CRORE, eps: 3.0 }),
    filing("2025-09-30", { revenue: 535 * CRORE, operating_profit: 120 * CRORE, net_profit: 80 * CRORE, eps: 2.1 }),
  ];
  const table = basisTable(filings, "2026-09-30", "consolidated");
  assert.deepEqual(
    table.columns.map((column) => column.label),
    ["Sep 2026", "Jun 2026", "Sep 2025"],
  );
  const revenue = table.rows[0];
  assert.equal(formatChange(revenue.yoy), "+34.4%");
  assert.equal(formatChange(revenue.qoq), "+7.3%");
  const operating = table.rows[1];
  assert.equal(operating.margin.label, "OPM");
  assert.equal(operating.margin.values[0].toFixed(1), "26.8");
  assert.equal(formatChange(operating.margin.yoy, " pp"), "+4.4 pp");
  assert.equal(table.documentUrl, "https://archive.example/2026-09-30.html");
});

test("figures are never compared across bases", () => {
  const filings = [
    filing("2026-09-30", { revenue: 200 }),
    filing("2025-09-30", { consolidated: false, revenue: 100 }),
  ];
  const table = basisTable(filings, "2026-09-30", "consolidated");
  assert.deepEqual(table.rows[0].values, [200, null, null]);
  assert.equal(table.rows[0].yoy, null);
});

test("there is no growth rate off a loss, and a missing line is not a zero", () => {
  const filings = [
    filing("2026-09-30", { revenue: 100, net_profit: 10 }),
    filing("2025-09-30", { revenue: 90, net_profit: -5 }),
  ];
  const [revenue, operating, net] = basisTable(filings, "2026-09-30", "consolidated").rows;
  assert.equal(net.yoy, null);
  assert.equal(operating.values[0], null);
  assert.equal(operating.margin.values[0], null);
  assert.ok(revenue.yoy > 11);
});

test("a card lists consolidated first and only the bases filed this quarter", () => {
  const filings = [
    filing("2026-09-30", { consolidated: false, revenue: 1 }),
    filing("2026-09-30", { revenue: 2 }),
    filing("2026-06-30", { consolidated: false, revenue: 1 }),
  ];
  const card = resultCard({ symbol: "AAA" }, filings, "2026-09-30");
  assert.deepEqual(card.bases.map((basis) => basis.basis), ["consolidated", "standalone"]);
  const standaloneOnly = resultCard({ symbol: "BBB" }, filings.slice(0, 1), "2026-09-30");
  assert.deepEqual(standaloneOnly.bases.map((basis) => basis.basis), ["standalone"]);
});

test("results are grouped by the day they were announced in the market's time", () => {
  const groups = groupByAnnouncedDay(
    [
      // 00:30 IST on the 15th is still the 14th in UTC.
      { symbol: "AAA", announced_at: "2026-10-14T19:00:00+00:00" },
      { symbol: "BBB", announced_at: "2026-10-14T18:00:00+00:00" },
      { symbol: "CCC", announced_at: "2026-10-14T10:00:00+00:00" },
    ],
    "Asia/Kolkata",
  );
  assert.deepEqual(
    groups.map((group) => [group.date, group.entries.map((entry) => entry.symbol)]),
    [
      ["2026-10-15", ["AAA"]],
      ["2026-10-14", ["BBB", "CCC"]],
    ],
  );
});

test("a row's decimals follow its largest figure", () => {
  assert.equal(amountDigits([1568 * CRORE, 42 * CRORE], CRORE), 0);
  assert.equal(amountDigits([42 * CRORE, null], CRORE), 1);
  assert.equal(amountDigits([4.2 * CRORE], CRORE), 2);
  assert.equal(formatChange(null), null);
  assert.equal(formatChange(-55.34), "-55.3%");
});
