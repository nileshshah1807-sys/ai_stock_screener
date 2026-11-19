import { test } from "node:test";
import assert from "node:assert/strict";

import {
  allotmentOdds,
  bookSize,
  categoryTimes,
  changeFromIssue,
  formatSignedPercent,
  formatTimes,
  groupIssues,
  impliedListing,
  issueStatus,
  minInvestment,
} from "./ipos.mjs";

// Shapes from workers/ipos.py's object on 18 Nov 2026.
const CRYSTAL = {
  symbol: "CRYSTALCP", open_date: "2026-11-18", close_date: "2026-11-20", listing_date: null,
  price_low: 259, price_high: 272, issue_price: null, lot_size: 55, book_shares: 12170076, gmp: 18,
  subscription: [{ category: "QIB", times: 2.07 }, { category: "Retail", times: 1.28 }],
};
const MAHACOAL = { symbol: "MAHACOAL", open_date: "2026-11-19", close_date: "2026-11-23", listing_date: null };
const VPFL = { symbol: "VPFL", open_date: "2026-11-02", close_date: "2026-11-04", listing_date: "2026-11-09", issue_price: 94 };
const BCSSL = { symbol: "BCSSL", open_date: "2026-10-29", close_date: "2026-11-02", listing_date: "2026-11-05", issue_price: 82 };

test("an issue's status follows its dates", () => {
  assert.equal(issueStatus(CRYSTAL, "2026-11-18"), "bidding");
  assert.equal(issueStatus(CRYSTAL, "2026-11-20"), "bidding");
  assert.equal(issueStatus(CRYSTAL, "2026-11-21"), "awaiting");
  assert.equal(issueStatus(MAHACOAL, "2026-11-18"), "upcoming");
  assert.equal(issueStatus(VPFL, "2026-11-18"), "listed");
  assert.equal(issueStatus({ ...VPFL, listing_date: "2026-11-25" }, "2026-11-18"), "awaiting");
});

test("issues group by status, listed newest first", () => {
  const groups = groupIssues([BCSSL, MAHACOAL, VPFL, CRYSTAL], "2026-11-18");
  assert.deepEqual(groups.bidding.map((r) => r.symbol), ["CRYSTALCP"]);
  assert.deepEqual(groups.upcoming.map((r) => r.symbol), ["MAHACOAL"]);
  assert.deepEqual(groups.listed.map((r) => r.symbol), ["VPFL", "BCSSL"]);
  assert.deepEqual(groups.awaiting, []);
});

test("money is worked out at the top of the band until the price is fixed", () => {
  assert.equal(minInvestment(CRYSTAL), 55 * 272);
  assert.equal(bookSize(CRYSTAL), 12170076 * 272);
  assert.equal(impliedListing(CRYSTAL), 290);
  assert.equal(minInvestment({ ...CRYSTAL, lot_size: null }), null);
  assert.equal(impliedListing({ ...CRYSTAL, gmp: null }), null);
  assert.ok(Math.abs(changeFromIssue(VPFL, 89.3) - -5) < 1e-9);
  assert.equal(changeFromIssue(VPFL, null), null);
});

test("a category with no ratio is absent, not zero", () => {
  assert.equal(categoryTimes(CRYSTAL, "Retail"), 1.28);
  assert.equal(categoryTimes(CRYSTAL, "NII"), null);
  assert.equal(categoryTimes({ subscription: null }, "QIB"), null);
});

test("allotment odds: certain at or under 1x, 1 - (1 - 1/R)^n above it", () => {
  assert.equal(allotmentOdds(0.8, 1), 1);
  assert.equal(allotmentOdds(4, 1), 0.25);
  assert.ok(Math.abs(allotmentOdds(4, 3) - (1 - 0.75 ** 3)) < 1e-12);
  assert.ok(Math.abs(allotmentOdds(1.38, 1) - 0.72464) < 1e-4); // Stocks Sena printed 72% for this book
  assert.equal(allotmentOdds(null, 1), null);
  assert.equal(allotmentOdds(4, 0), null);
});

test("ratios and changes print with a true minus and two places", () => {
  assert.equal(formatTimes(1.4), "1.40×");
  assert.equal(formatTimes(null), null);
  assert.equal(formatSignedPercent(-5), "−5.0%");
  assert.equal(formatSignedPercent(6.99, 2), "+6.99%");
  assert.equal(formatSignedPercent(0), "0.0%");
});
