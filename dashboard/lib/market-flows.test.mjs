import assert from "node:assert/strict";
import test from "node:test";

import { FLOW_BARS, flowSummary, indexFuturesPositioning } from "./market-flows.mjs";

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

test("index-futures positioning reads the latest session, in participant order", () => {
  const oi = (date, category, long, short) => ({ session_date: date, category, future_index_long: long, future_index_short: short });
  const p = indexFuturesPositioning([oi("2026-11-17", "FII", 1, 1), oi("2026-11-18", "Pro", 30, 10), oi("2026-11-18", "FII", 25, 75), oi("2026-11-18", "Client", 0, 0)]);
  assert.equal(p.date, "2026-11-18");
  assert.deepEqual(p.participants, [
    { category: "Client", long: 0, short: 0, net: 0, longShare: null },
    { category: "FII", long: 25, short: 75, net: -50, longShare: 0.25 },
    { category: "Pro", long: 30, short: 10, net: 20, longShare: 0.75 },
  ]);
  assert.equal(indexFuturesPositioning([]), null);
});
