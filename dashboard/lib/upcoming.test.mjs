import assert from "node:assert/strict";
import { test } from "node:test";

import {
  callTime,
  filterUpcoming,
  groupUpcoming,
  sortUpcoming,
  upcomingResultDate,
  upcomingSummary,
} from "./upcoming.mjs";

const call = (symbol, event_date, event_time = null) => ({ kind: "call", symbol, company: symbol, event_date, event_time });

test("past days drop out and a call with no time follows the timed ones of its day", () => {
  const rows = [
    call("C", "2026-11-02"),
    call("B", "2026-11-02", "2026-11-02T12:00:00+05:30"),
    call("A", "2026-11-02", "2026-11-02T10:00:00+05:30"),
    call("OLD", "2026-10-30"),
  ];
  assert.deepEqual(sortUpcoming(rows, "2026-10-31").map((row) => row.symbol), ["A", "B", "C"]);
});

test("empty days fold into one gap, and today stays even when empty", () => {
  const groups = groupUpcoming([call("A", "2026-11-03"), call("B", "2026-11-05")], "2026-10-31");
  assert.deepEqual(
    groups.map((g) => (g.gap ? `gap ${g.from}..${g.to} (${g.days})` : `${g.date}${g.isToday ? " today" : ""} ${g.rows.length}`)),
    ["2026-10-31 today 0", "gap 2026-11-01..2026-11-02 (2)", "2026-11-03 1", "gap 2026-11-04..2026-11-04 (1)", "2026-11-05 1"],
  );
});

test("nothing upcoming still gives today as the one day", () => {
  assert.deepEqual(groupUpcoming([], "2026-10-31"), [{ date: "2026-10-31", isToday: true, rows: [] }]);
});

test("search matches symbol or company; a watchlist keeps only its symbols", () => {
  const rows = [
    { kind: "results", symbol: "TCS", company: "Tata Consultancy", event_date: "2026-11-03", event_time: null },
    { kind: "results", symbol: "INFY", company: "Infosys", event_date: "2026-11-03", event_time: null },
  ];
  assert.deepEqual(filterUpcoming(rows, { search: " tata " }).map((r) => r.symbol), ["TCS"]);
  assert.deepEqual(filterUpcoming(rows, { symbols: ["INFY"] }).map((r) => r.symbol), ["INFY"]);
  assert.deepEqual(filterUpcoming(rows, { symbols: [] }), []);
});

test("a call time is India's clock; none stated gives null", () => {
  assert.equal(callTime("2026-11-05T12:00:00+05:30"), "12:00");
  assert.equal(callTime("2026-11-05T06:30:00Z"), "12:00");
  assert.equal(callTime(null), null);
  assert.equal(callTime("nonsense"), null);
});

test("the next call skips one already over today; untimed calls still count", () => {
  const rows = [call("A", "2026-10-31", "2026-10-31T09:00:00+05:30"), call("B", "2026-10-31", "2026-10-31T16:00:00+05:30")];
  const now = new Date("2026-10-31T11:00:00+05:30");
  assert.equal(upcomingSummary(rows, "2026-10-31", now).next.symbol, "B");
  assert.equal(upcomingSummary([call("U", "2026-10-31")], "2026-10-31", now).next.symbol, "U");
  assert.equal(upcomingSummary([], "2026-10-31", now).next, null);
});

test("a company's coming result date is its first row from today", () => {
  const rows = [
    { kind: "results", symbol: "TCS", event_date: "2026-10-20" },
    { kind: "results", symbol: "TCS", event_date: "2026-11-04" },
  ];
  assert.equal(upcomingResultDate(rows, "TCS", "2026-10-31"), "2026-11-04");
  assert.equal(upcomingResultDate(rows, "INFY", "2026-10-31"), null);
});
