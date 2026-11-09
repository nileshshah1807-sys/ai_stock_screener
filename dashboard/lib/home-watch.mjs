/**
 * The arithmetic behind the Home page's watchlist cards. Pure, so it is
 * tested with node --test; the reads are in `home-watch.ts`.
 */

import { monthsBefore } from "./financials.mjs";

/** A shareholding move smaller than this many percentage points is rounding, not news. */
export const MIN_MOVE_POINTS = 0.1;
/** Sessions back for the 1W and 1M returns. */
export const WEEK_SESSIONS = 5;
export const MONTH_SESSIONS = 21;
/** A deals feed whose newest day is older than this many days is called late. */
export const DEALS_LAG_DAYS = 4;

const days = (a, b) => Math.round((Date.parse(`${a}T00:00:00Z`) - Date.parse(`${b}T00:00:00Z`)) / 86_400_000);

/** The year-on-year growth of revenue and net profit on a result card's first basis. */
export function resultGrowth(card) {
  const basis = card.bases[0];
  const yoy = (key) => basis?.rows.find((row) => row.key === key)?.yoy ?? null;
  return { basis: basis?.basis ?? null, revenue: yoy("revenue"), profit: yoy("net_profit") };
}

/**
 * Each symbol's latest shareholding filing against the quarter before it, as
 * changes in percentage points; only symbols where a group moved by
 * `MIN_MOVE_POINTS`, biggest mover first. A missing prior quarter or group is
 * left out, never read as zero.
 */
export function shareholdingMoves(rows) {
  const bySymbol = new Map();
  for (const row of rows) bySymbol.set(row.symbol, [...(bySymbol.get(row.symbol) ?? []), row]);
  const moves = [];
  for (const [symbol, filings] of bySymbol) {
    const latest = filings.reduce((a, b) => (b.period_end > a.period_end ? b : a));
    const before = filings.find((row) => row.period_end === monthsBefore(latest.period_end, 3));
    if (!before) continue;
    const change = (key) =>
      latest[key] == null || before[key] == null ? null : Math.round((latest[key] - before[key]) * 100) / 100;
    const changes = { promoter: change("promoter"), fii: change("fii"), dii: change("dii") };
    const size = Math.max(0, ...Object.values(changes).map((value) => Math.abs(value ?? 0)));
    if (size >= MIN_MOVE_POINTS) moves.push({ symbol, company: latest.company ?? null, period: latest.period_end, size, ...changes });
  }
  return moves.sort((a, b) => b.size - a.size || a.symbol.localeCompare(b.symbol));
}

/** How late the deals feed runs: the days since its newest deal, or null while it is current. */
export function dealsLag(newestDealDate, today) {
  if (!newestDealDate) return null;
  const lag = days(today, newestDealDate);
  return lag > DEALS_LAG_DAYS ? lag : null;
}

/** Deal value in the market's currency, quantity times price. */
export const dealValue = (deal) => Number(deal.quantity) * Number(deal.price);

/**
 * 1W and 1M returns (percent) and the closes of the last month for a trend
 * line, from ascending closes; null where the history is too short.
 */
export function windowReturns(closes) {
  const last = closes.at(-1);
  const since = (sessions) => {
    const base = closes.at(-1 - sessions);
    return last == null || !(base > 0) ? null : ((last / base) - 1) * 100;
  };
  return { week: since(WEEK_SESSIONS), month: since(MONTH_SESSIONS), trend: closes.slice(-(MONTH_SESSIONS + 1)) };
}

/** The same returns with a live price standing in for the last close. */
export function liveReturns(closes, price) {
  return windowReturns(price > 0 ? [...closes, price] : closes);
}

/** An SVG polyline `points` string fitting `values` into width x height; "" for fewer than two. */
export function trendPoints(values, width, height) {
  if (values.length < 2) return "";
  const low = Math.min(...values);
  const span = Math.max(...values) - low || 1;
  return values
    .map((value, index) => `${((index / (values.length - 1)) * width).toFixed(1)},${(height - ((value - low) / span) * height).toFixed(1)}`)
    .join(" ");
}
