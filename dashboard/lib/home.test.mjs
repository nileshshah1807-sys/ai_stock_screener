import assert from "node:assert/strict";
import test from "node:test";

import { cardsFor, isScreenerQuery, screenerRedirect } from "./home.mjs";

test("a viewer with no watchlist sees the market cards only", () => {
  assert.deepEqual(cardsFor("NSE", false), ["pulse", "movers", "breadth", "results-season", "lined-up"]);
});

test("a watcher sees their cards first, then the market's", () => {
  const ids = cardsFor("NSE", true);
  assert.equal(ids[0], "since");
  assert.ok(ids.indexOf("watchlist-today") < ids.indexOf("pulse"));
});

test("US has no shareholding or deals card, with or without a watchlist", () => {
  for (const watching of [true, false]) {
    const ids = cardsFor("US", watching);
    assert.ok(!ids.includes("shareholding") && !ids.includes("deals"));
  }
  assert.ok(cardsFor("US", true).includes("since"));
});

test("an old screener link keeps its filters on the new path", () => {
  assert.equal(isScreenerQuery({}), false);
  assert.equal(isScreenerQuery({ rating: "BUY" }), true);
  assert.equal(isScreenerQuery({ utm_source: "x" }), false);
  assert.equal(isScreenerQuery({ utm_source: "x", page: "2" }), true);
  assert.equal(screenerRedirect("/ind", { rating: "BUY", sector: ["A", "B"], q: undefined }), "/ind/screener?rating=BUY&sector=A&sector=B");
  assert.equal(screenerRedirect("/us", {}), "/us/screener");
});

test("bars share one scale per card and never pass it", async () => {
  const { barScale, barShare, columnCards, groupEventsByDate } = await import("./home.mjs");
  assert.equal(barScale([2, -8, null, 4]), 8);
  assert.equal(barScale([0, 0]), 1);
  assert.equal(barShare(-4, 8), 50);
  assert.equal(barShare(20, 8), 100);
  assert.equal(barShare(null, 8), 0);
  assert.deepEqual(columnCards(["since", "pulse", "coming-up", "deals", "breadth"]), ["since", "deals"]);
  const days = groupEventsByDate([{ event_date: "2026-11-12", s: 1 }, { event_date: "2026-11-10", s: 2 }, { event_date: "2026-11-12", s: 3 }]);
  assert.deepEqual(days.map((d) => [d.date, d.events.length]), [["2026-11-10", 1], ["2026-11-12", 2]]);
});
