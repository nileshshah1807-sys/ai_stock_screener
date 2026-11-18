import assert from "node:assert/strict";
import test from "node:test";

import { FLOW_BARS, flowSummary, flowYears } from "./market-flows.mjs";

const flow = (date, category, net_value) => ({ session_date: date, category, net_value });

test("flowSummary pairs FII and DII per session, oldest first", () => {
  const s = flowSummary([flow("2026-11-18", "FII", -100), flow("2026-11-17", "DII", 50), flow("2026-11-18", "DII", 200), flow("2026-11-17", "FII", 10)]);
  assert.equal(s.date, "2026-11-18");
  assert.deepEqual(s.bars, [
    { date: "2026-11-17", fii: 10, dii: 50 },
    { date: "2026-11-18", fii: -100, dii: 200 },
  ]);
});

test("five-day and month-to-date nets cover their own sessions only", () => {
  const rows = [];
  ["2026-10-30", "2026-10-31", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"].forEach((d, i) => {
    rows.push(flow(d, "FII", i + 1), flow(d, "DII", -(i + 1)));
  });
  const s = flowSummary(rows);
  assert.deepEqual(s.fiveDay, { sessions: 5, fii: 2 + 3 + 4 + 5 + 6, dii: -(2 + 3 + 4 + 5 + 6) });
  assert.deepEqual(s.monthToDate, { sessions: 4, fii: 3 + 4 + 5 + 6, dii: -(3 + 4 + 5 + 6) });
});

test("an unreported value is absent, not zero; a side never reported sums to null", () => {
  const s = flowSummary([flow("2026-11-18", "FII", null), flow("2026-11-18", "DII", 5), { session_date: "2026-11-18", category: "Other", net_value: 9 }]);
  assert.deepEqual(s.bars, [{ date: "2026-11-18", fii: null, dii: 5 }]);
  assert.equal(s.fiveDay.fii, null);
});

test("bars keep the newest FLOW_BARS sessions; no rows is null", () => {
  const rows = Array.from({ length: FLOW_BARS + 5 }, (_, i) => flow(`2026-01-${String(i + 1).padStart(2, "0")}`, "FII", i));
  assert.equal(flowSummary(rows).bars.length, FLOW_BARS);
  assert.equal(flowSummary(rows).bars[0].date, "2026-01-06");
  assert.equal(flowSummary([]), null);
  assert.equal(flowSummary(null), null);
});

test("flowYears pairs FII and DII per year, newest first; nothing is null", () => {
  const y = (year, category, net_value, sessions) => ({ year, category, net_value, sessions, buy_value: 1, sell_value: 1 });
  assert.deepEqual(flowYears([y(2025, "FII", -10.5, 249), y(2026, "DII", 30, 220), y(2026, "FII", 5, 220), y(2025, "DII", null, 249), y(2025, "Other", 1, 1)]), [
    { year: 2026, fii: 5, dii: 30, sessions: 220 },
    { year: 2025, fii: -10.5, dii: null, sessions: 249 },
  ]);
  assert.equal(flowYears([]), null);
  assert.equal(flowYears(undefined), null);
});
