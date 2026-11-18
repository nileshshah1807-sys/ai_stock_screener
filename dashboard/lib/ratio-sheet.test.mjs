import assert from "node:assert/strict";
import test from "node:test";

import { valuation } from "./live-compute.mjs";
import { basisSource, peerComparison, ratioHistory, ratioInputs } from "./ratio-sheet.mjs";

const basis = { shares_outstanding: 100, net_profit_ttm: 500, book_equity: 2000, ebitda_ttm: 800, total_debt: 300, total_cash: 100 };

test("each ratio equals the tile's (live-compute valuation) at the same price", () => {
  const tile = valuation({ price: 50, change_pct: 1 }, basis);
  assert.equal(ratioInputs("pe_ratio", 50, 1, basis).value, tile.pe_ratio);
  assert.equal(ratioInputs("pb_ratio", 50, 1, basis).value, tile.pb_ratio);
  assert.equal(ratioInputs("ev_ebitda", 50, 1, basis).value, tile.ev_ebitda);
  assert.equal(ratioInputs("market_cap", 50, 1, basis).value, tile.market_cap);
});

test("the steps show the inputs: EPS for P/E, EV from debt and cash", () => {
  const pe = Object.fromEntries(ratioInputs("pe_ratio", 50, 1, basis).steps.map((s) => [s.label, s.value]));
  assert.equal(pe["Market cap"], 5000);
  assert.equal(pe["Earnings per share"], 5);
  const ev = Object.fromEntries(ratioInputs("ev_ebitda", 50, 1, basis).steps.map((s) => [s.label, s.value]));
  assert.equal(ev["Enterprise value"], 5200);
});

test("a withheld change of unit or a missing basis gives no ratio, not zero", () => {
  assert.equal(ratioInputs("pe_ratio", 50, null, basis).value, null);
  assert.equal(ratioInputs("pe_ratio", 50, 1, null).value, null);
  assert.equal(ratioInputs("ev_ebitda", 50, 1, { ...basis, total_cash: null }).value, null);
});

test("history median skips gaps; current is placed against it", () => {
  const h = ratioHistory([{ period_end: "a", pe: 10 }, { period_end: "b", pe: null }, { period_end: "c", pe: 30 }, { period_end: "d", pe: 20 }], "pe_ratio", 22);
  assert.equal(h.points.length, 4);
  assert.equal(h.median, 20);
  assert.ok(Math.abs(h.vsMedian - 0.1) < 1e-12);
  assert.equal(ratioHistory([{ period_end: "a", pe: -5 }], "pe_ratio", 3).vsMedian, null);
  assert.deepEqual(ratioHistory(undefined, "pe_ratio", 3), { points: [], median: null, vsMedian: null });
});

test("peers sort by market cap and give their median", () => {
  const p = peerComparison({ industry: "IT", rows: [{ symbol: "B", market_cap: 1, pe: 30 }, { symbol: "A", company: "Alpha", market_cap: 9, pe: 10 }, { symbol: "C", market_cap: 5, pe: null }] }, "pe_ratio");
  assert.deepEqual(p.rows.map((r) => r.symbol), ["A", "C", "B"]);
  assert.equal(p.rows[0].company, "Alpha");
  assert.equal(p.median, 20);
  assert.deepEqual(peerComparison(null, "pe_ratio"), { industry: null, rows: [], median: null });
});

test("the source reads as filed quarters or vendor figures", () => {
  assert.equal(basisSource({ source: "filings", quarters: ["2026-06-30", "2026-09-30"], statement_basis: "consolidated" }), "Trailing 2 filed quarters to 2026-09-30, consolidated");
  assert.equal(basisSource({ source: "yahoo", quarters: [], period_end: "2026-09-30" }), "Latest reported figures to 2026-09-30");
  assert.equal(basisSource(null), null);
});
