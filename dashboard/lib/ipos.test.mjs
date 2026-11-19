import { test } from "node:test";
import assert from "node:assert/strict";

import {
  allotmentOdds,
  boardParam,
  bookSize,
  categoryTimes,
  listQuery,
  listedColumns,
  onBoard,
  changeFromIssue,
  formatSignedPercent,
  formatTimes,
  gmpStamp,
  groupIssues,
  impliedListing,
  periodLabel,
  issueStatus,
  minInvestment,
  splitRisks,
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

test("a GMP's time reads as the hour today and with its day before", () => {
  assert.equal(gmpStamp("2026-11-19T11:02:00+05:30", "2026-11-19"), "11:02");
  assert.equal(gmpStamp("2026-11-18T19:37:00+05:30", "2026-11-19"), "18 Nov, 19:37");
  assert.equal(gmpStamp(null, "2026-11-19"), null);
  assert.equal(periodLabel("2026-06-30"), "Jun 2026");
});

test("the board filter keeps one board, and an unnamed board only under all", () => {
  const rows = [
    { symbol: "CRYSTALCP", board: "Mainboard" },
    { symbol: "WATRANA", board: "SME" },
    { symbol: "ODD", board: null },
  ];
  assert.deepEqual(onBoard(rows, "sme").map((r) => r.symbol), ["WATRANA"]);
  assert.deepEqual(onBoard(rows, "mainboard").map((r) => r.symbol), ["CRYSTALCP"]);
  assert.equal(onBoard(rows, "all").length, 3);
  assert.equal(boardParam("sme"), "sme");
  assert.equal(boardParam("SME"), "all");
  assert.equal(boardParam(undefined), "all");
});

test("the list's query carries the board and show-all, and nothing by default", () => {
  assert.equal(listQuery("all", false), "");
  assert.equal(listQuery("sme", false), "?board=sme");
  assert.equal(listQuery("mainboard", true), "?board=mainboard&listed=all");
  assert.equal(listQuery("all", true), "?listed=all");
});

test("a listed column no shown row has a value for is left out", () => {
  const sme = [{ symbol: "HGSINDIALT", subscription_total: null }, { symbol: "MAXENGS", subscription_total: null }];
  assert.deepEqual(listedColumns(sme, new Map()), { subscribed: false, now: false });
  const mixed = [...sme, { symbol: "VPFL", subscription_total: 12.4 }];
  assert.deepEqual(listedColumns(mixed, new Map([["MAXENGS", 160]])), { subscribed: true, now: true });
});

test("an RHP's risk factors show the first five; the rest fold away", () => {
  const risks = Array.from({ length: 78 }, (_, i) => ({ title: `Risk ${i + 1}.`, text: null }));
  const { lead, more } = splitRisks(risks);
  assert.deepEqual(lead.map((risk) => risk.title), ["Risk 1.", "Risk 2.", "Risk 3.", "Risk 4.", "Risk 5."]);
  assert.equal(more.length, 73);
  assert.deepEqual(splitRisks(risks.slice(0, 3)), { lead: risks.slice(0, 3), more: [] });
  assert.deepEqual(splitRisks(null), { lead: [], more: [] });
});
