import assert from "node:assert/strict";
import { test } from "node:test";

import {
  defaultRules,
  eventFilterEntries,
  feedSymbols,
  industryOptions,
  intersectSymbols,
  isDefaultView,
  matchSymbols,
  parseEventFilters,
  ruleLabel,
  withLists,
} from "./event-filters.mjs";

const KINDS = { param: "kind", options: [{ value: "results" }, { value: "transcript" }] };
const wholeMarket = { market: "NSE", listIds: ["a", "b"], defaultScope: "all", facets: [KINDS] };
const watchlistsFirst = { ...wholeMarket, defaultScope: "watchlists" };

const CAP_FLOOR = [{ metric: "mcap", op: "gte", value: 1000 }];

test("a whole-market feed opens above the size floor", () => {
  const filters = parseEventFilters({}, wholeMarket);
  assert.deepEqual(filters.rules, CAP_FLOOR);
  assert.deepEqual(filters.lists, []);
  assert.equal(isDefaultView(filters, wholeMarket), true);
});

test("a feed scoped to watchlists opens with no floor", () => {
  const filters = parseEventFilters({}, watchlistsFirst);
  assert.deepEqual(filters.lists, ["a", "b"]);
  assert.deepEqual(filters.rules, []);
  assert.equal(isDefaultView(filters, watchlistsFirst), true);
  assert.deepEqual(defaultRules("NSE", true), []);
});

test("scope=all still means the whole market, and brings the floor with it", () => {
  const filters = parseEventFilters({ scope: "all" }, watchlistsFirst);
  assert.deepEqual(filters.lists, []);
  assert.deepEqual(filters.rules, CAP_FLOOR);
  assert.deepEqual(eventFilterEntries(filters, watchlistsFirst), [["scope", "all"]]);
});

test("a viewer with no lists has no scope to spell out", () => {
  const context = { ...watchlistsFirst, listIds: [] };
  const filters = parseEventFilters({}, context);
  assert.deepEqual(filters.rules, CAP_FLOOR);
  assert.deepEqual(eventFilterEntries(filters, context), []);
});

test("removing every rule is spelled out, so it survives a reload", () => {
  const filters = { ...parseEventFilters({}, wholeMarket), rules: [] };
  assert.deepEqual(eventFilterEntries(filters, wholeMarket), [["f", "none"]]);
  assert.deepEqual(parseEventFilters({ f: "none" }, wholeMarket).rules, []);
});

test("rules round-trip through the URL and malformed ones are dropped", () => {
  const filters = parseEventFilters({ f: "mcap.gte.5000,pe.lte.22.5,bogus.gte.1,mcap.gte." }, wholeMarket);
  assert.deepEqual(filters.rules, [
    { metric: "mcap", op: "gte", value: 5000 },
    { metric: "pe", op: "lte", value: 22.5 },
  ]);
  assert.deepEqual(eventFilterEntries(filters, wholeMarket), [["f", "mcap.gte.5000,pe.lte.22.5"]]);
});

test("lists, industries and facets are repeated params; unknown values are dropped", () => {
  const filters = parseEventFilters(
    { list: ["b", "gone"], industry: ["Banks, Regional", "Steel"], kind: ["results", "other"] },
    wholeMarket,
  );
  assert.deepEqual(filters.lists, ["b"]);
  assert.deepEqual(filters.industries, ["Banks, Regional", "Steel"]);
  assert.deepEqual(filters.facets, { kind: ["results"] });
  // A list is chosen, so the floor is not the default and is not spelled out.
  assert.deepEqual(eventFilterEntries(filters, wholeMarket), [
    ["list", "b"],
    ["industry", "Banks, Regional"],
    ["industry", "Steel"],
    ["kind", "results"],
  ]);
});

test("one list of several is named; all of them is the watchlist default", () => {
  const one = parseEventFilters({ list: "a" }, watchlistsFirst);
  assert.deepEqual(eventFilterEntries(one, watchlistsFirst), [["list", "a"]]);
  const all = parseEventFilters({ list: ["a", "b"] }, watchlistsFirst);
  assert.deepEqual(eventFilterEntries(all, watchlistsFirst), []);
});

const COMPANIES = [
  { symbol: "BIG", industry: "Steel", market_cap: 5e11, pe_ratio: 12 },
  { symbol: "MID", industry: "Steel", market_cap: 1e10, pe_ratio: 40 },
  { symbol: "SMALL", industry: "Banks", market_cap: 2e9, pe_ratio: 8 },
  { symbol: "UNKNOWN", industry: "Banks", market_cap: null, pe_ratio: null },
];

test("a size is compared in the market's unit, at the boundary inclusive", () => {
  const symbols = matchSymbols(COMPANIES, { rules: CAP_FLOOR, industries: [] }, "NSE");
  assert.deepEqual([...symbols], ["BIG", "MID"]);
});

test("an unreported figure passes neither a floor nor a ceiling", () => {
  const ceiling = [{ metric: "mcap", op: "lte", value: 1000 }];
  const symbols = matchSymbols(COMPANIES, { rules: ceiling, industries: [] }, "NSE");
  assert.deepEqual([...symbols], ["MID", "SMALL"]);
});

test("rules and industries narrow together; neither means no restriction", () => {
  const filters = { rules: [{ metric: "pe", op: "lte", value: 20 }], industries: ["Steel"] };
  assert.deepEqual([...matchSymbols(COMPANIES, filters, "NSE")], ["BIG"]);
  assert.equal(matchSymbols(COMPANIES, { rules: [], industries: [] }, "NSE"), null);
});

test("intersecting keeps null as no restriction", () => {
  assert.equal(intersectSymbols(null, null), null);
  assert.deepEqual([...intersectSymbols(new Set(["A", "B"]), null)], ["A", "B"]);
  assert.deepEqual([...intersectSymbols(null, ["A"])], ["A"]);
  assert.deepEqual([...intersectSymbols(new Set(["A", "B"]), ["B", "C"])], ["B"]);
});

test("industries are counted and listed by name", () => {
  assert.deepEqual(industryOptions(COMPANIES), [
    { value: "Banks", label: "Banks", count: 2 },
    { value: "Steel", label: "Steel", count: 2 },
  ]);
});

test("a rule reads in the market's own unit", () => {
  assert.equal(ruleLabel(CAP_FLOOR[0], "NSE"), "Market cap ≥ ₹1,000 Cr");
  assert.equal(ruleLabel({ metric: "mcap", op: "gte", value: 100 }, "US"), "Market cap ≥ $100 M");
  assert.equal(ruleLabel({ metric: "pe", op: "lte", value: 25 }, "US"), "P/E ≤ 25");
});

test("choosing a list takes the default floor off; a rule the viewer set stays", () => {
  const open = parseEventFilters({}, wholeMarket);
  assert.deepEqual(withLists(open, ["a"], "NSE").rules, []);
  assert.deepEqual(withLists(withLists(open, ["a"], "NSE"), [], "NSE").rules, CAP_FLOOR);

  const own = parseEventFilters({ f: "mcap.gte.5000" }, wholeMarket);
  assert.deepEqual(withLists(own, ["a"], "NSE").rules, own.rules);
});

const LISTS = [
  { id: "a", symbols: ["BIG", "SMALL"] },
  { id: "b", symbols: ["MID"] },
];

test("a feed is read for the chosen lists' companies that pass the filters", () => {
  const none = { rules: [], industries: [], lists: [], facets: {} };
  assert.equal(feedSymbols(none, LISTS, COMPANIES, "NSE"), null);
  assert.deepEqual(feedSymbols({ ...none, lists: ["a"] }, LISTS, COMPANIES, "NSE"), ["BIG", "SMALL"]);
  assert.deepEqual(
    feedSymbols({ ...none, lists: ["a"], rules: CAP_FLOOR }, LISTS, COMPANIES, "NSE"),
    ["BIG"],
  );
});

test("with no run to test against, rules are not applied rather than emptying the feed", () => {
  const filters = { rules: CAP_FLOOR, industries: ["Steel"], lists: [], facets: {} };
  assert.equal(feedSymbols(filters, LISTS, null, "NSE"), null);
  assert.deepEqual(feedSymbols({ ...filters, lists: ["b"] }, LISTS, null, "NSE"), ["MID"]);
});

test("each market's floor is stated in its own unit", () => {
  assert.deepEqual(defaultRules("US", false), [{ metric: "mcap", op: "gte", value: 1000 }]);
  assert.equal(ruleLabel(defaultRules("US", false)[0], "US"), "Market cap ≥ $1,000 M");
});

test("growth rules are read only where the page offers them, and never tested against the run", () => {
  const url = { f: "mcap.gte.1000,revyoy.gte.15,patqoq.lte.-5" };
  assert.deepEqual(parseEventFilters(url, wholeMarket).rules, CAP_FLOOR);
  const withGrowth = parseEventFilters(url, { ...wholeMarket, growth: true });
  assert.deepEqual(withGrowth.rules.map((rule) => rule.metric), ["mcap", "revyoy", "patqoq"]);
  // A run's facts say nothing of growth: the rule is the page's to apply.
  const companies = [{ symbol: "A", market_cap: 2000 * 1e7 }, { symbol: "B", market_cap: 10 * 1e7 }];
  assert.deepEqual([...matchSymbols(companies, withGrowth, "NSE")], ["A"]);
  assert.equal(matchSymbols(companies, { rules: [withGrowth.rules[1]], industries: [] }, "NSE"), null);
  assert.equal(ruleLabel({ metric: "patqoq", op: "lte", value: -5 }, "NSE"), "PAT growth QoQ ≤ -5%");
});
