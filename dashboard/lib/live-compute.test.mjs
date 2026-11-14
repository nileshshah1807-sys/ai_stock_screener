import assert from "node:assert/strict";
import { test } from "node:test";

import { liveBreadth, liveMarket, valuation } from "./live-compute.mjs";

const at = "2026-11-14T09:00:00+00:00";
const stock = (symbol, price, change_pct, session = "2026-11-14") => ({ kind: "stock", symbol, price, change_pct, volume: 1, traded_at: at, session, fetched_at: at });

test("valuation: the view's ratios at the quote, none for a withheld change", () => {
  const basis = { shares_outstanding: 10, net_profit_ttm: 50, book_equity: 0, ebitda_ttm: 20, total_debt: 30, total_cash: 10 };
  const row = valuation(stock("A", 100, 1.5), basis);
  assert.deepEqual([row.market_cap, row.pe_ratio, row.pb_ratio, row.ev_ebitda], [1000, 20, null, 51]);
  assert.equal(valuation(stock("A", 100, null), basis).market_cap, null);
  assert.equal(valuation(stock("A", 100, 1), null).pe_ratio, null);
});

test("liveMarket: movers of today's session by index, rated from the run, no rating", () => {
  const quotes = [
    stock("A", 10, 2),
    stock("B", 20, -1),
    stock("C", 30, 0),
    stock("D", 40, 5, "2026-11-13"),
    { kind: "index", symbol: "Nifty 50", price: 24000, change_pct: 0.4, session: "2026-11-14" },
  ];
  const members = ["A", "B", "C", "D"].map((symbol) => ({ index_name: "Nifty 50", symbol, company: `${symbol} Ltd`, position: 1 }));
  const { session, indices } = liveMarket(quotes, members, 10, new Set(["A"]));
  assert.equal(session, "2026-11-14");
  const [index] = indices;
  assert.deepEqual([index.members, index.level, index.advances, index.declines, index.unchanged], [4, 24000, 1, 1, 1]);
  assert.deepEqual(index.gainers, [{ symbol: "A", company: "A Ltd", price: 10, change_pct: 2, rated: true, rating: null }]);
  assert.deepEqual(index.losers.map((row) => [row.symbol, row.rated]), [["B", false]]);
});

test("liveBreadth: counts against the charted session's levels only", () => {
  const quotes = [stock("A", 110, 1), stock("B", 90, -1), { kind: "index", symbol: "NIFTY", price: 105, change_pct: 1, session: "2026-11-14" }];
  const level = (symbol, extra) => ({
    symbol, as_of: "2026-11-13", sector: "IT", e20: 100, e50: 100, e100: null, e200: 100, hi: 105, lo: 95, base: 100, bench_label: "NIFTY", bench_base: 100, ...extra,
  });
  const levels = [level("A"), level("B", { sector: "Banks" })];
  const all = liveBreadth(quotes, levels, "2026-11-13", "market", "");
  assert.deepEqual(all.counts, { n: 2, e20: 1, e20d: 2, e50: 1, e50d: 2, e100: 0, e100d: 0, e200: 1, e200d: 2, hi: 1, lo: 1, hld: 2, bb: 1, bbd: 2 });
  assert.equal(liveBreadth(quotes, levels, "2026-11-13", "sector", "IT").counts.n, 1);
  assert.equal(liveBreadth(quotes, levels, "2026-11-12", "market", "").counts, null);
});
