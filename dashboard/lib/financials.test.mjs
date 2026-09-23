import assert from "node:assert/strict";
import test from "node:test";

import {
  availableViews,
  buildColumns,
  buildView,
  findPeriod,
  growth,
  monthsBefore,
  periodLabel,
} from "./financials.mjs";

// TCS's real shape: Yahoo has no Sep 2025 column.
const TCS_QUARTERS = ["2025-03-31", "2025-06-30", "2025-12-31", "2026-03-31", "2026-06-30"];

function payload(quarterly, annual = {}) {
  return { v: 1, quarterly: { income: quarterly }, annual };
}

test("period labels and month arithmetic land on month ends", () => {
  assert.equal(periodLabel("2026-06-30"), "Jun 2026");
  assert.equal(monthsBefore("2026-06-30", 3), "2026-03-31");
  assert.equal(monthsBefore("2026-06-30", 12), "2025-06-30");
  assert.equal(monthsBefore("2026-03-31", 1), "2026-02-28");
  assert.equal(monthsBefore("2025-12-31", -3), "2026-03-31");
});

test("periods match by date within tolerance, not by position", () => {
  assert.equal(findPeriod(TCS_QUARTERS, "2025-12-31"), 2);
  assert.equal(findPeriod(TCS_QUARTERS, "2026-04-02"), 3);
  assert.equal(findPeriod(TCS_QUARTERS, "2025-09-30"), -1);
});

test("a skipped quarter becomes a gap column", () => {
  const columns = buildColumns(TCS_QUARTERS, { quarterly: true });
  assert.deepEqual(
    columns.map((c) => [c.label, c.source]),
    [
      ["Mar 2025", 0],
      ["Jun 2025", 1],
      ["Sep 2025", null],
      ["Dec 2025", 2],
      ["Mar 2026", 3],
      ["Jun 2026", 4],
    ],
  );
});

test("annual columns are not gap-filled", () => {
  const columns = buildColumns(["2023-03-31", "2025-03-31"], { quarterly: false });
  assert.equal(columns.length, 2);
});

test("growth needs both values and a positive base", () => {
  assert.equal(growth(110, 100), 10);
  assert.equal(growth(90, 100), -10);
  assert.equal(growth(10, -50), null);
  assert.equal(growth(10, 0), null);
  assert.equal(growth(null, 100), null);
  assert.equal(growth(100, null), null);
});

test("QoQ compares against the quarter three months back, skipping gaps honestly", () => {
  const view = buildView(
    payload({
      periods: TCS_QUARTERS,
      rows: { revenue: [100, 110, 120, 130, 143], net_profit: [1, 1, 1, 1, 1] },
    }),
    "quarterly",
  );
  const qoq = view.rows.find((row) => row.label === "Revenue QoQ").cells;
  // Dec 2025's previous quarter (Sep) is the gap, so its QoQ is unknown --
  // not a comparison against Jun, six months back.
  assert.deepEqual(
    qoq.map((v) => (v == null ? null : Math.round(v * 10) / 10)),
    [null, 10, null, null, 8.3, 10],
  );
  const yoy = view.rows.find((row) => row.label === "Revenue YoY").cells;
  assert.deepEqual(
    yoy.map((v) => (v == null ? null : Math.round(v * 10) / 10)),
    [null, null, null, null, 30, 30],
  );
});

test("rows with nothing reported are dropped; margins derive from their lines", () => {
  const view = buildView(
    payload({
      periods: ["2026-06-30"],
      rows: { revenue: [200], operating_profit: [50], net_profit: [20] },
    }),
    "quarterly",
  );
  const labels = view.rows.map((row) => row.label);
  assert.ok(!labels.includes("Depreciation"));
  assert.ok(!labels.includes("Revenue QoQ"));
  assert.equal(view.rows.find((row) => row.label === "OPM").cells[0], 25);
  assert.equal(view.rows.find((row) => row.label === "NPM").cells[0], 10);
});

test("CFO / net profit reads net profit from the income statement by date", () => {
  const view = buildView(
    payload(
      { periods: [], rows: {} },
      {
        income: { periods: ["2025-03-31", "2026-03-31"], rows: { net_profit: [50, 80] } },
        cashflow: { periods: ["2026-03-31"], rows: { cfo: [100] } },
      },
    ),
    "cash_flow",
  );
  assert.equal(view.rows.find((row) => row.label === "CFO / net profit").cells[0], 125);
});

test("available views skip statements with no periods", () => {
  assert.deepEqual(
    availableViews(
      payload(
        { periods: ["2026-06-30"], rows: { revenue: [1] } },
        { income: { periods: [], rows: {} }, cashflow: { periods: ["2026-03-31"], rows: { cfo: [1] } } },
      ),
    ),
    ["quarterly", "cash_flow"],
  );
  assert.deepEqual(availableViews(null), []);
});
