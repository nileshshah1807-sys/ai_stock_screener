import assert from "node:assert/strict";
import test from "node:test";

import { inSession, quoteFreshness } from "./live-quotes.mjs";
import { dayAt, noticeDismissKey, noticeText, tradingHours } from "./market-calendar.mjs";

const NSE = {
  timezone: "Asia/Kolkata",
  timezoneLabel: "IST",
  locale: "en-IN",
  sessionOpen: "09:15",
  sessionClose: "15:30",
};
const HOLIDAY = { day: "2026-11-10", kind: "holiday", reason: "Guru Nanak Jayanti", sessionOpen: null, sessionClose: null };
const MUHURAT = { day: "2026-11-08", kind: "special_session", reason: "Muhurat trading", sessionOpen: "18:00", sessionClose: "19:00" };

// Tuesday 10 Nov 2026, 11:45 IST, and Sunday 8 Nov 2026, 18:30 IST.
const TUE = Date.parse("2026-11-10T06:15:00Z");
const SUN_EVENING = Date.parse("2026-11-08T13:00:00Z");
const SUN_NOON = Date.parse("2026-11-08T06:15:00Z");
const LAST_TRADE = "2026-11-09T09:55:00Z";

test("a normal day, or no calendar row, keeps the regular hours", () => {
  assert.equal(inSession(TUE, NSE), true);
  assert.equal(inSession(TUE, NSE, null), true);
  assert.deepEqual(tradingHours(NSE, null), { open: "09:15", close: "15:30" });
  assert.equal(noticeText(null, "IST"), null);
  assert.equal(quoteFreshness(LAST_TRADE, LAST_TRADE, NSE, TUE).label, "Delayed · last trade 9 Nov, 15:25 IST");
  assert.equal(quoteFreshness(LAST_TRADE, LAST_TRADE, NSE, SUN_NOON).label, "Market closed · last trade 9 Nov, 15:25 IST");
});

test("a weekday holiday is closed all day, with the reason", () => {
  assert.equal(inSession(TUE, NSE, HOLIDAY), false);
  assert.equal(tradingHours(NSE, HOLIDAY), null);
  assert.equal(noticeText(HOLIDAY, "IST"), "Market closed today: Guru Nanak Jayanti");
  const { state, label } = quoteFreshness(LAST_TRADE, LAST_TRADE, NSE, TUE, HOLIDAY);
  assert.equal(state, "closed");
  assert.match(label, /^Market closed: Guru Nanak Jayanti · last trade /);
});

test("a special session is open in its own hours, even on a Sunday", () => {
  assert.equal(inSession(SUN_EVENING, NSE, MUHURAT), true);
  assert.equal(inSession(SUN_EVENING, NSE, null), false);
  assert.equal(inSession(Date.parse("2026-11-08T11:00:00Z"), NSE, MUHURAT), false); // 16:30, before it opens
  assert.equal(noticeText(MUHURAT, "IST"), "Special session: Muhurat trading, 18:00-19:00 IST");
  assert.equal(quoteFreshness("2026-11-08T05:00:00Z", LAST_TRADE, NSE, SUN_EVENING, MUHURAT).state, "delayed");
});

test("a row for another day says nothing about today", () => {
  assert.equal(dayAt(HOLIDAY, TUE, NSE.timezone), HOLIDAY);
  assert.equal(dayAt(HOLIDAY, TUE + 86_400_000, NSE.timezone), null);
  assert.equal(inSession(TUE + 86_400_000, NSE, HOLIDAY), true);
});

test("the dismissal is per market and per day", () => {
  assert.notEqual(noticeDismissKey("NSE", "2026-11-10"), noticeDismissKey("US", "2026-11-10"));
  assert.notEqual(noticeDismissKey("NSE", "2026-11-10"), noticeDismissKey("NSE", "2026-11-11"));
});
