/**
 * The maths behind the Home page's market cards. Pure, so `node --test` runs
 * it; the reads that feed it are in home-market.ts.
 */

import { pointAt, rangeStart } from "./market-breadth.mjs";

/** Percent change from `from` to `to`; null when either is missing or `from` is not positive. */
export function pctChange(from, to) {
  if (!Number.isFinite(from) || !Number.isFinite(to) || from <= 0) return null;
  return (to / from - 1) * 100;
}

/**
 * The closes an index's changes are measured from: the last bar, the one
 * before it, and the bars a week and a month earlier (the last on or before
 * that date, so a holiday borrows the prior close). Null for a series too
 * short to have a last bar.
 *
 * @param {{time: string, value: number}[]} points oldest first
 */
export function pulseBases(points) {
  const last = points.at(-1);
  if (!last) return null;
  const at = (date) => pointAt(points, date)?.value ?? null;
  return {
    last,
    prev: points.length > 1 ? points.at(-2).value : null,
    week: at(rangeStart(last.time, null, 7)),
    month: at(rangeStart(last.time, 1, null)),
  };
}

/**
 * Largest rises and falls in net profit, year on year, among result cards
 * (`resultCard`). The rate is the one the card prints, on the basis it opens
 * on; a loss for a base or a missing line has no rate and is left out.
 */
export function profitMovers(cards, limit) {
  const rated = cards
    .map((card) => ({
      symbol: card.symbol,
      company: card.company ?? null,
      change: card.bases[0]?.rows.find((row) => row.key === "net_profit")?.yoy,
      // A rate needs a positive base, so a negative profit here is a company that fell into loss.
      loss: (card.bases[0]?.rows.find((row) => row.key === "net_profit")?.values?.[0] ?? 0) < 0,
    }))
    .filter((row) => Number.isFinite(row.change));
  const byChange = (a, b) => b.change - a.change;
  return {
    rises: rated.filter((row) => row.change > 0).sort(byChange).slice(0, limit),
    falls: rated.filter((row) => row.change < 0).sort((a, b) => -byChange(a, b)).slice(0, limit),
  };
}

/**
 * One-month gainers and losers inside each index.
 *
 * @param {Map<string, string[]>} members symbols by index name
 * @param {{symbol: string, pct_change_1m: number | null}[]} rows the run's stocks
 * @returns {Map<string, {gainers: object[], losers: object[]}>}
 */
export function monthlyMovers(members, rows, limit) {
  const bySymbol = new Map(rows.filter((row) => Number.isFinite(row.pct_change_1m)).map((row) => [row.symbol, row]));
  const out = new Map();
  for (const [name, symbols] of members) {
    const priced = symbols.map((symbol) => bySymbol.get(symbol)).filter(Boolean);
    priced.sort((a, b) => b.pct_change_1m - a.pct_change_1m);
    out.set(name, {
      gainers: priced.filter((row) => row.pct_change_1m > 0).slice(0, limit),
      losers: priced.filter((row) => row.pct_change_1m < 0).slice(-limit).reverse(),
    });
  }
  return out;
}
