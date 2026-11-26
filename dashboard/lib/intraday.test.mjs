import assert from "node:assert/strict";
import { test } from "node:test";

import { dayBase, intradayFor, intradayGeometry, marketDate, withLivePoint } from "./intraday.mjs";

const NIFTY = { name: "Nifty 50", points: [[1000, 101], [1300, 103]] };
const OBJECT = { session: "2026-11-26", rows: [NIFTY, { name: "Nifty 500", points: [] }] };

test("the market's date is the exchange's, not the viewer's", () => {
  // 20:00 UTC on the 26th is already the 27th in India.
  assert.equal(marketDate(Date.UTC(2026, 10, 26, 20), "Asia/Kolkata"), "2026-11-27");
  assert.equal(marketDate(Date.UTC(2026, 10, 26, 20), "America/New_York"), "2026-11-26");
});

test("a line shows only on its own session's day, and only with points", () => {
  assert.equal(intradayFor(OBJECT, "Nifty 50", "2026-11-26"), NIFTY);
  assert.equal(intradayFor(OBJECT, "Nifty 50", "2026-11-27"), null);
  assert.equal(intradayFor(OBJECT, "Nifty 500", "2026-11-26"), null);
  assert.equal(intradayFor(OBJECT, "Nifty Bank", "2026-11-26"), null);
  assert.equal(intradayFor(null, "Nifty 50", "2026-11-26"), null);
});

test("the live level joins the line only when it is newer than the last bar", () => {
  const iso = (seconds) => new Date(seconds * 1000).toISOString();
  assert.deepEqual(withLivePoint(NIFTY.points, 104, iso(1500)), [...NIFTY.points, [1500, 104]]);
  assert.equal(withLivePoint(NIFTY.points, 104, iso(1300)), NIFTY.points);
  assert.equal(withLivePoint(NIFTY.points, null, iso(1500)), NIFTY.points);
  assert.equal(withLivePoint(NIFTY.points, 104, null), NIFTY.points);
  assert.deepEqual(withLivePoint([], 104, iso(1500)), []);
});

test("a morning's line fills only the morning's share of the session", () => {
  // 09:15 to 15:30 is 375 minutes; an hour in is 16% of the width.
  const geometry = intradayGeometry([[0, 100], [3600, 102]], { base: 100, sessionOpen: "09:15", sessionClose: "15:30", width: 375, height: 40 });
  assert.equal(geometry.last[0], 60);
  assert.equal(geometry.rising, true);
  // The previous close is the low here, so its line sits on the bottom edge.
  assert.equal(geometry.baseY, 38);
});

test("below the previous close the line falls, and the close stays inside the box", () => {
  const geometry = intradayGeometry([[0, 99], [300, 97]], { base: 100, sessionOpen: "09:30", sessionClose: "16:00", width: 100, height: 40 });
  assert.equal(geometry.rising, false);
  assert.equal(geometry.baseY, 2);
  assert.equal(intradayGeometry([], { base: 100, sessionOpen: "09:30", sessionClose: "16:00", width: 100, height: 40 }), null);
});

test("a session longer than the stated hours still fits the box", () => {
  const geometry = intradayGeometry([[0, 1], [30_000, 2]], { base: null, sessionOpen: "09:15", sessionClose: "10:15", width: 100, height: 40 });
  assert.equal(geometry.last[0], 100);
  assert.equal(geometry.baseY, null);
});

test("the baseline is the close the tile's 1D implies", () => {
  // 26 Nov 2026: Nifty 50 at 25,884.50, +0.25% on 25,819.25.
  assert.ok(Math.abs(dayBase(25884.5, 0.2527) - 25819.25) < 0.05);
  assert.equal(dayBase(25884.5, null), null);
  assert.equal(dayBase(25884.5, undefined), null);
  assert.equal(dayBase(25884.5, -100), null);
});
