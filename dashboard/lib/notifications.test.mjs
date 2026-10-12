import assert from "node:assert/strict";
import test from "node:test";

import {
  badgeText,
  describeEvent,
  eventTime,
  groupByDay,
  isUnread,
  quarterLabel,
} from "./notifications.mjs";

const event = (values) => ({
  id: 1,
  symbol: "AAA",
  kind: "results",
  event_key: "2026-09-30",
  occurred_at: "2026-10-08T16:37:30+00:00",
  detected_at: "2026-10-09T03:05:00+00:00",
  detail: { period: "2026-09-30", source: "filing" },
  ...values,
});

test("a quarter end is labelled from the string, not through a time zone", () => {
  assert.equal(quarterLabel("2026-09-30"), "Sep 2026");
  assert.equal(quarterLabel("2026-03-31T00:00:00+00:00"), "Mar 2026");
  assert.equal(quarterLabel(null), null);
  assert.equal(quarterLabel("Q2"), null);
});

test("a filed result points at the financials tab", () => {
  assert.deepEqual(describeEvent(event({})), {
    title: "Results filed",
    summary: "Quarter ended Sep 2026",
    tab: "financials",
  });
});

test("a result with no filing index is published, not filed", () => {
  const described = describeEvent(event({ detail: { period: "2026-09-30", source: "vendor" } }));
  assert.equal(described.title, "Results published");
});

test("a transcript names its quarter when it has one", () => {
  const withQuarter = describeEvent(
    event({ kind: "transcript", detail: { quarter: "2026-09-30", call_date: "2026-10-09" } }),
  );
  assert.equal(withQuarter.title, "Earnings call transcript");
  assert.equal(withQuarter.summary, "Sep 2026 quarter");
  assert.equal(describeEvent(event({ kind: "transcript", detail: {} })).summary, null);
});

test("an unknown kind still renders, by its name", () => {
  assert.equal(describeEvent(event({ kind: "board_meeting" })).title, "Board meeting");
});

test("unread is measured on when the event was recorded", () => {
  // Filed on the 8th, recorded on the 9th; the viewer looked in between.
  assert.equal(isUnread(event({}), "2026-10-08T20:00:00+00:00"), true);
  assert.equal(isUnread(event({}), "2026-10-09T04:00:00+00:00"), false);
  assert.equal(isUnread(event({}), null), true);
});

test("the two timestamp spellings Postgres returns compare correctly", () => {
  const micros = event({ detected_at: "2026-10-09T03:05:00.123456+00:00" });
  assert.equal(isUnread(micros, "2026-10-09T03:05:00Z"), true);
});

test("the badge stops at nine and is absent at zero", () => {
  assert.equal(badgeText(0), null);
  assert.equal(badgeText(3), "3");
  assert.equal(badgeText(9), "9");
  assert.equal(badgeText(42), "9+");
});

test("the time shown is the exchange's clock", () => {
  assert.equal(eventTime("2026-10-08T16:37:30+00:00", "Asia/Kolkata"), "22:07");
  assert.equal(eventTime("2026-10-08T16:37:30+00:00", "America/New_York"), "12:37");
  assert.equal(eventTime("nonsense", "Asia/Kolkata"), null);
});

test("events group by the exchange's calendar day, newest first", () => {
  const events = [
    event({ id: 1, occurred_at: "2026-10-12T05:00:00+00:00" }),
    // 19:30 UTC on the 11th is already the 12th in India.
    event({ id: 2, occurred_at: "2026-10-11T19:30:00+00:00" }),
    event({ id: 3, occurred_at: "2026-10-11T05:00:00+00:00" }),
    event({ id: 4, occurred_at: "2026-10-08T16:37:30+00:00" }),
  ];
  const groups = groupByDay(events, "Asia/Kolkata", new Date("2026-10-12T06:00:00+00:00"));
  assert.deepEqual(
    groups.map((group) => [group.label, group.events.map((e) => e.id)]),
    [
      ["Today", [1, 2]],
      ["Yesterday", [3]],
      ["8 Oct 2026", [4]],
    ],
  );
});
