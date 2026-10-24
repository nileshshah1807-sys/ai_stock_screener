import assert from "node:assert/strict";
import test from "node:test";

import {
  LIVE_FOR_MS,
  MIN_POLL_MS,
  REFRESH_MS,
  inSession,
  isLive,
  liveOverlay,
  ratioOverlay,
  nextPollDelay,
  quoteFreshness,
  quoteTime,
  tickDirection,
} from "./live-quotes.mjs";

const WRITTEN = "2026-10-16T06:15:00Z";
const at = (minutes) => Date.parse(WRITTEN) + minutes * 60_000;

test("the next poll lands just after the worker's next run", () => {
  const right = nextPollDelay(WRITTEN, at(0));
  assert.ok(right > REFRESH_MS && right < REFRESH_MS + 60_000);
  // Four minutes in, about a minute and a bit is left.
  const later = nextPollDelay(WRITTEN, at(4));
  assert.ok(later > 60_000 && later < 2 * 60_000);
});

test("an overdue run is asked about at the floor, not in a tight loop", () => {
  assert.equal(nextPollDelay(WRITTEN, at(7)), MIN_POLL_MS);
});

test("a shut market is checked rarely", () => {
  assert.equal(nextPollDelay(WRITTEN, at(LIVE_FOR_MS / 60_000 + 1)), 15 * 60_000);
  assert.equal(nextPollDelay(null, at(0)), 15 * 60_000);
  assert.equal(nextPollDelay("garbage", at(0)), 15 * 60_000);
});

test("live means written on one of the last few runs", () => {
  assert.equal(isLive(WRITTEN, at(19)), true);
  assert.equal(isLive(WRITTEN, at(21)), false);
  assert.equal(isLive(null, at(0)), false);
});

test("a quote's ratios replace the close's from the row's own session on", () => {
  const quote = { session: "2026-10-16", pe_ratio: 56.2 };
  assert.equal(ratioOverlay(quote, "2026-10-15"), quote);
  // A result filed after the evening run: same session, newer basis.
  assert.equal(ratioOverlay(quote, "2026-10-16"), quote);
  assert.equal(ratioOverlay(quote, "2026-10-17"), null);
  assert.equal(ratioOverlay(null, "2026-10-15"), null);
});

test("a quote replaces the close only when it is from a later session", () => {
  const quote = { session: "2026-10-16", price: 101 };
  assert.equal(liveOverlay(quote, "2026-10-15"), quote);
  // The evening run has published today's close: the row's own figure stands.
  assert.equal(liveOverlay(quote, "2026-10-16"), null);
  assert.equal(liveOverlay(null, "2026-10-15"), null);
  assert.equal(liveOverlay(quote, null), quote);
});

test("quote times read in the exchange's clock", () => {
  // 06:14 UTC is 11:44 in India.
  assert.equal(quoteTime("2026-10-16T06:14:00Z", "Asia/Kolkata", "en-IN", at(1)), "11:44");
  // A day later the date is shown too.
  const tomorrow = at(24 * 60);
  assert.match(quoteTime("2026-10-16T06:14:00Z", "Asia/Kolkata", "en-IN", tomorrow), /16 Oct, 11:44/);
  assert.equal(quoteTime(null, "Asia/Kolkata", "en-IN", at(0)), "");
});

test("a price that moved tints its way; the first read and a repeat do not", () => {
  assert.equal(tickDirection(100, 101.5), "up");
  assert.equal(tickDirection(100, 99.95), "down");
  assert.equal(tickDirection(100, 100), null);
  assert.equal(tickDirection(undefined, 100), null);
  assert.equal(tickDirection(null, 100), null);
  assert.equal(tickDirection(100, Number.NaN), null);
});

const NSE_CLOCK = {
  timezone: "Asia/Kolkata",
  timezoneLabel: "IST",
  locale: "en-IN",
  sessionOpen: "09:15",
  sessionClose: "15:30",
};

test("the session is the exchange's weekday hours, in its own clock", () => {
  // Friday 16 Oct 2026: 11:45 IST is in, 15:45 IST and 09:00 IST are out.
  assert.equal(inSession(Date.parse("2026-10-16T06:15:00Z"), NSE_CLOCK), true);
  assert.equal(inSession(Date.parse("2026-10-16T10:15:00Z"), NSE_CLOCK), false);
  assert.equal(inSession(Date.parse("2026-10-16T03:30:00Z"), NSE_CLOCK), false);
  // Saturday, in hours.
  assert.equal(inSession(Date.parse("2026-10-17T06:15:00Z"), NSE_CLOCK), false);
});

test("a stopped quote reads closed outside the session and delayed inside it", () => {
  const live = quoteFreshness(WRITTEN, WRITTEN, NSE_CLOCK, at(5));
  assert.equal(live.state, "live");
  assert.match(live.label, /^Live 11:45 IST$/);

  const delayed = quoteFreshness(WRITTEN, WRITTEN, NSE_CLOCK, at(60));
  assert.equal(delayed.state, "delayed");
  assert.match(delayed.label, /^Delayed · last trade 11:45 IST$/);

  const closed = quoteFreshness(WRITTEN, WRITTEN, NSE_CLOCK, Date.parse("2026-10-17T06:15:00Z"));
  assert.equal(closed.state, "closed");
  assert.match(closed.label, /^Market closed · last trade 16 Oct, 11:45 IST$/);
});
