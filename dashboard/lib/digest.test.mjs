import assert from "node:assert/strict";
import { test } from "node:test";

import { bearerMatches } from "./bearer.mjs";
import { DIGEST_KEYS, digestFrom } from "./digest.mjs";

// Delta-encoded the way market_breadth stores them (lib/market-breadth.mjs decodeRow).
const breadthRow = {
  sessions: JSON.stringify([20404, 1]),
  series: JSON.stringify({ e50: [40, 5], e50d: [100, 0], e200: [30, 0], e200d: [100, 0], s2: [10, 2], hi: [3, 1], lo: [2, -1] }),
};

const input = {
  market: "NSE",
  slug: "ind",
  today: "2026-11-13",
  through: "2026-11-20",
  feed: [{ symbol: "MMFL", period_end: "2026-09-30", announced_at: "2026-11-13T10:00:00Z", company: "MM Forgings", has_consolidated: false, has_standalone: true }],
  filings: [
    { symbol: "MMFL", period_end: "2026-09-30", is_consolidated: false, filed_at: null, document_url: null, lines: { revenue: 120, net_profit: 11 } },
    { symbol: "MMFL", period_end: "2025-09-30", is_consolidated: false, filed_at: null, document_url: null, lines: { revenue: 100, net_profit: 10 } },
  ],
  calls: [{ symbol: "ASTRAMICRO", company: "Astra Microwave", call_date: "2026-11-13", management_stance: "Bullish", management_stance_quote: "Order book doubled", outlook_score: 80, tone_score: 70 }],
  breadthRow,
  // Extra columns must never pass through, whatever a read adds later.
  snapshot: [
    { symbol: "MMFL", company: "MM Forgings", stage: "Stage 2", days_in_stage: 0, pct_change_1d: 2.5, investment_rank: 4, rating: "BUY", final_score: 88 },
    { symbol: "TCS", company: "TCS", stage: "Stage 2", days_in_stage: 40, pct_change_1d: -1 },
  ],
  upcoming: [
    { symbol: "TCS", next_result_date: "2026-11-15", next_call_at: null, next_call_date: null },
    { symbol: "LATE", next_result_date: "2026-12-30", next_call_at: null, next_call_date: null },
  ],
};

test("the digest carries exactly its keys: no rating, rank, score or return", () => {
  const digest = digestFrom(input);
  const keys = (value) => Object.keys(value).sort();
  assert.deepEqual(keys(digest), [...DIGEST_KEYS.top].sort());
  for (const section of ["results", "concalls", "upcoming"]) {
    assert.ok(digest[section].length, section);
    for (const row of digest[section]) assert.deepEqual(keys(row), [...DIGEST_KEYS[section]].sort());
  }
  assert.deepEqual(keys(digest.stage2), [...DIGEST_KEYS.stage2].sort());
  for (const row of digest.stage2.new_entrants) assert.deepEqual(keys(row), [...DIGEST_KEYS.entrant].sort());
  assert.deepEqual(keys(digest.breadth), [...DIGEST_KEYS.breadth].sort());
  assert.doesNotMatch(JSON.stringify(digest), /rating|rank|score|return/i);
});

test("the digest's figures come from the rows it is given", () => {
  const digest = digestFrom(input);
  assert.equal(digest.results[0].revenue_yoy_pct, 20);
  assert.equal(digest.results[0].profit_yoy_pct, 10);
  assert.equal(digest.results[0].page_url, "https://cupel.in/ind/stocks/MMFL");
  assert.equal(digest.concalls[0].stance_band, "Bullish");
  assert.deepEqual(digest.stage2, { count: 12, change_vs_prev: 2, new_entrants: [{ symbol: "MMFL", name: "MM Forgings" }] });
  assert.deepEqual(digest.breadth, { pct_above_50ema: 45, pct_above_200ema: 30, advancers: 1, decliners: 1, new_52w_highs: 4, new_52w_lows: 1 });
  assert.deepEqual(digest.upcoming.map((row) => [row.symbol, row.name]), [["TCS", "TCS"]]);
});

test("the bearer check opens only for the configured token", () => {
  assert.equal(bearerMatches("Bearer s3cret", "s3cret"), true);
  assert.equal(bearerMatches("Bearer wrong!", "s3cret"), false);
  assert.equal(bearerMatches(null, "s3cret"), false);
  assert.equal(bearerMatches("Bearer ", undefined), false);
  assert.equal(bearerMatches("Bearer undefined", undefined), false);
});
