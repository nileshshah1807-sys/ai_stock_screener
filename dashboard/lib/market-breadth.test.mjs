import assert from "node:assert/strict";
import test from "node:test";

import {
  decodeRow,
  indexPoints,
  metricPoints,
  niceScale,
  pointAt,
  rangeStart,
  sliceFrom,
  timeTicks,
} from "./market-breadth.mjs";

/** Mirror of workers/market_breadth.py `_delta_list`. */
function delta(values) {
  return values.map((value, index) => (index === 0 ? value : value - values[index - 1]));
}

const DAY = 86_400_000;
const days = (dates) => dates.map((date) => Date.parse(`${date}T00:00:00Z`) / DAY);

function row(dates, series) {
  return {
    sessions: JSON.stringify(delta(days(dates))),
    series: JSON.stringify(
      Object.fromEntries(Object.entries(series).map(([key, values]) => [key, delta(values)])),
    ),
  };
}

test("a row decodes to its dates and absolute counts", () => {
  const dates = ["2026-09-16", "2026-09-17", "2026-09-18"];
  const decoded = decodeRow(row(dates, { e50: [10, 12, 9], e50d: [20, 20, 21] }));
  assert.deepEqual(decoded.dates, dates);
  assert.deepEqual(decoded.series.e50, [10, 12, 9]);
  assert.deepEqual(decoded.series.e50d, [20, 20, 21]);
});

test("a misaligned or malformed row is rejected, not half-drawn", () => {
  const dates = ["2026-09-17", "2026-09-18"];
  assert.equal(decodeRow(row(dates, { e50: [1, 2, 3] })), null);
  assert.equal(decodeRow({ sessions: "[1,", series: "{}" }), null);
  assert.equal(decodeRow(null), null);
});

test("a share is taken against the metric's own denominator", () => {
  const decoded = decodeRow(
    row(["2026-09-17", "2026-09-18"], { s2: [5, 6], s2d: [20, 24] }),
  );
  const share = metricPoints(decoded, "s2", "s2d", "share");
  assert.deepEqual(share.map((point) => point.value), [25, 25]);
  const count = metricPoints(decoded, "s2", "s2d", "count");
  assert.deepEqual(count.map((point) => point.value), [5, 6]);
});

test("a session with nothing measured is a gap, not 0%", () => {
  const decoded = decodeRow(
    row(["2026-09-16", "2026-09-17", "2026-09-18"], { e200: [0, 0, 3], e200d: [0, 0, 6] }),
  );
  const points = metricPoints(decoded, "e200", "e200d", "share");
  assert.equal(points.length, 1);
  assert.equal(points[0].time, "2026-09-18");
});

test("index levels come back from hundredths", () => {
  const decoded = decodeRow(row(["2026-09-17", "2026-09-18"], { c: [2412345, 2419900] }));
  assert.deepEqual(indexPoints(decoded).map((point) => point.value), [24123.45, 24199]);
});

test("a range start steps back calendar months and clamps month ends", () => {
  assert.equal(rangeStart("2026-09-18", 6), "2026-03-18");
  assert.equal(rangeStart("2026-03-31", 1), "2026-02-28");
  assert.equal(rangeStart("2026-09-18", null), null);
});

test("slicing keeps the range and never returns an empty chart", () => {
  const points = ["2026-01-01", "2026-02-01", "2026-03-01"].map((time) => ({ time }));
  assert.deepEqual(sliceFrom(points, "2026-01-15").map((p) => p.time), ["2026-02-01", "2026-03-01"]);
  assert.equal(sliceFrom(points, "2027-01-01").length, 1);
  assert.equal(sliceFrom(points, null).length, 3);
});

test("a hovered date reads the last known value, never tomorrow's", () => {
  const points = [
    { time: "2026-09-16", value: 1 },
    { time: "2026-09-18", value: 3 },
  ];
  assert.equal(pointAt(points, "2026-09-17").value, 1);
  assert.equal(pointAt(points, "2026-09-18").value, 3);
  assert.equal(pointAt(points, "2026-09-15"), null);
});

test("a share axis stays inside 0-100 on round steps", () => {
  const scale = niceScale(3, 97, { clamp: [0, 100] });
  assert.equal(scale.min, 0);
  assert.equal(scale.max, 100);
  assert.deepEqual(scale.ticks, [0, 25, 50, 75, 100]);
  const level = niceScale(22480, 24830);
  assert.ok(level.min <= 22480 && level.max >= 24830);
  assert.ok(level.ticks.length >= 3 && level.ticks.length <= 7);
});

test("month ticks carry the year only where it changes", () => {
  const ticks = timeTicks("2025-10-10", "2026-09-18");
  assert.ok(ticks.length <= 6);
  const labels = ticks.map((tick) => tick.label);
  assert.ok(labels.includes("Jan 2026"));
  assert.ok(labels[0].includes("20"), "first tick names its year");
});

test("a short range ticks weeks and a long one ticks years", () => {
  const weeks = timeTicks("2026-08-18", "2026-09-18");
  assert.ok(weeks.length >= 3 && weeks.every((tick) => /^\d+ [A-Z][a-z]{2}$/.test(tick.label)));
  const years = timeTicks("2018-01-01", "2026-09-18");
  assert.ok(years.every((tick) => /^\d{4}$/.test(tick.label)));
  assert.ok(years.length <= 6);
});
