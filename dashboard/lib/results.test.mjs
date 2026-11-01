import assert from "node:assert/strict";
import { test } from "node:test";

import {
  amountDigits,
  basisTable,
  bucketOf,
  chosenQuarter,
  formatChange,
  groupByAnnouncedDay,
  chosenSpan,
  median,
  passesGrowth,
  quarterEnds,
  quarterWindow,
  quarterMedians,
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
    filing("2025-09-30", { revenue: 90, operating_profit: 20, net_profit: -5 }),
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

test("a company that has just begun to consolidate opens on standalone", () => {
  // SGFIN, Oct 2026: its first consolidated quarter, a year of standalone ones.
  const filings = [
    filing("2026-09-30", { revenue: 161 }),
    filing("2026-09-30", { consolidated: false, revenue: 161 }),
    filing("2025-09-30", { consolidated: false, revenue: 75 }),
  ];
  const card = resultCard({ symbol: "SGFIN" }, filings, "2026-09-30");
  assert.deepEqual(card.bases.map((basis) => basis.basis), ["standalone", "consolidated"]);
  assert.ok(card.bases[0].rows[0].yoy > 100);
  // Once the consolidated year-ago quarter is there, consolidated leads again.
  const later = resultCard({ symbol: "SGFIN" }, [...filings, filing("2025-09-30", { revenue: 75 })], "2026-09-30");
  assert.equal(later.bases[0].basis, "consolidated");
});

test("a bank's card has net interest income and no operating profit", () => {
  const filings = [filing("2026-09-30", { revenue: 1584, net_interest_income: 1116, net_profit: 426, eps: 1.62 })];
  const rows = basisTable(filings, "2026-09-30", "consolidated").rows;
  assert.deepEqual(rows.map((row) => row.key), ["revenue", "net_interest_income", "net_profit", "eps"]);
});

test("a growth rule tests the rate the card prints, on the basis it opens on", () => {
  const filings = [
    filing("2026-09-30", { revenue: 120 * CRORE, operating_profit: 30 * CRORE, net_profit: 20 * CRORE }),
    filing("2026-06-30", { revenue: 100 * CRORE, operating_profit: 20 * CRORE, net_profit: 25 * CRORE }),
    filing("2025-09-30", { revenue: 80 * CRORE, operating_profit: 30 * CRORE, net_profit: -5 * CRORE }),
  ];
  const card = resultCard({ symbol: "ABC" }, filings, "2026-09-30");
  const rule = (metric, op, value) => ({ metric, op, value });
  // Revenue is up 50% on the year and 20% on the quarter.
  assert.equal(passesGrowth(card, [rule("revyoy", "gte", 50)]), true);
  assert.equal(passesGrowth(card, [rule("revyoy", "gte", 51)]), false);
  assert.equal(passesGrowth(card, [rule("revqoq", "gte", 20), rule("opqoq", "gte", 50)]), true);
  // PAT fell on the quarter, and the year-ago quarter was a loss: no rate, so no rule passes.
  assert.equal(passesGrowth(card, [rule("patqoq", "lte", -10)]), true);
  assert.equal(passesGrowth(card, [rule("patyoy", "gte", -1000)]), false);
  assert.equal(passesGrowth(card, [rule("patyoy", "lte", 1000)]), false);
  // Rules that are not about growth are not this function's to judge.
  assert.equal(passesGrowth(card, [rule("mcap", "gte", 10 ** 9)]), true);
  assert.equal(passesGrowth(card, []), true);
});

test("a company that did not file the quarter on any basis passes no growth rule", () => {
  const card = resultCard({ symbol: "ABC" }, [], "2026-09-30");
  assert.equal(passesGrowth(card, [{ metric: "revyoy", op: "gte", value: -100 }]), false);
});

const filed = (symbol, period_end, revenue, net_profit = 10) => ({
  symbol,
  period_end,
  is_consolidated: true,
  lines: { revenue, net_profit },
});

test("quarterMedians takes the median rate of those who reported, oldest first", () => {
  const filings = [
    filed("A", "2026-09-30", 120), filed("A", "2025-09-30", 100),
    filed("B", "2026-09-30", 150), filed("B", "2025-09-30", 100),
    filed("C", "2026-09-30", 90), filed("C", "2025-09-30", 100),
    // reported, but nothing a year earlier: counts as a result, not in the median
    filed("D", "2026-09-30", 500),
  ];
  const [older, newer] = quarterMedians(filings, ["2026-09-30", "2026-06-30"]);
  assert.equal(older.quarter, "2026-06-30");
  assert.equal(older.results, 0);
  assert.equal(older.series.revenue.median, null);
  assert.equal(newer.results, 4);
  assert.deepEqual(newer.series.revenue, { median: 20, n: 3 });
  assert.deepEqual(newer.series.operating_profit, { median: null, n: 0 });
});

test("quarterMedians keeps to the companies in scope", () => {
  const filings = [
    filed("A", "2026-09-30", 120), filed("A", "2025-09-30", 100),
    filed("B", "2026-09-30", 300), filed("B", "2025-09-30", 100),
  ];
  const [only] = quarterMedians(filings, ["2026-09-30"], new Set(["A"]));
  assert.equal(only.results, 1);
  assert.equal(only.series.revenue.median, 20);
});

test("median and chosenSpan", () => {
  assert.equal(median([]), null);
  assert.equal(median([3, 1, 2, 4]), 2.5);
  assert.equal(chosenSpan("8"), 8);
  assert.equal(chosenSpan("5"), 6);
  assert.equal(chosenSpan(undefined), 6);
});

test("a filing that reports neither revenue nor net profit is not a result, as in the feed view", () => {
  const filings = [
    filed("A", "2026-09-30", 120), filed("A", "2025-09-30", 100),
    { symbol: "B", period_end: "2026-09-30", is_consolidated: true, lines: { revenue: null, net_profit: null } },
    { symbol: "C", period_end: "2026-09-30", is_consolidated: true, lines: { revenue: null, net_profit: 5 } },
  ];
  const [only] = quarterMedians(filings, ["2026-09-30"]);
  assert.equal(only.results, 2);
});

test("a US calendar quarter holds the fiscal quarters ending within 45 days of it", () => {
  assert.deepEqual(quarterWindow("2026-09-30"), { after: "2026-08-14", through: "2026-11-14" });
  const ends = ["2026-09-30", "2026-06-30"];
  assert.equal(bucketOf("2026-08-31", ends), "2026-09-30");
  assert.equal(bucketOf("2026-11-14", ends), "2026-09-30");
  assert.equal(bucketOf("2026-08-14", ends), "2026-06-30");
  assert.equal(bucketOf("2026-08-15", ends), "2026-09-30");
  assert.equal(bucketOf("2026-11-15", ends), null);
});

test("every date across a year is in exactly one quarter window", () => {
  const ends = quarterEnds("2027-12-31", 8);
  for (let day = Date.parse("2026-03-01T00:00:00Z"); day < Date.parse("2027-03-01T00:00:00Z"); day += 86_400_000) {
    const date = new Date(day).toISOString().slice(0, 10);
    const holding = ends.filter((end) => bucketOf(date, [end]));
    assert.equal(holding.length, 1, date);
  }
});

test("a 52-week filer's quarter finds the previous and year-ago quarters a few days off the month", () => {
  const filings = [
    filing("2025-09-27", { revenue: 100 }),
    filing("2025-06-28", { revenue: 80 }),
    filing("2024-09-28", { revenue: 50 }),
  ];
  const [table] = resultCard({ symbol: "AAPL" }, filings, "2025-09-27").bases;
  const revenue = table.rows.find((row) => row.key === "revenue");
  assert.deepEqual(revenue.values, [100, 80, 50]);
  assert.equal(revenue.yoy, 100);
  assert.equal(revenue.qoq, 25);
  assert.deepEqual(table.columns.map((column) => column.period), ["2025-09-27", "2025-06-28", "2024-09-28"]);
});
