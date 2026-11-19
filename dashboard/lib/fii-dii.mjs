/**
 * FII/DII cash-market flows as workers/market_flows.py writes them to
 * `live/NSE/fii-dii-flows.json`: one row per session and category, values in
 * rupees crore. Kept free of React so `node --test` can exercise it.
 */

export const CATEGORIES = ["FII", "DII"];

const num = (value) => {
  const n = typeof value === "number" ? value : Number.parseFloat(value);
  return Number.isFinite(n) ? n : null;
};

/**
 * Sessions oldest first, each `{ session, FII, DII }` where a category is
 * `{ buy, sell, net }` or null when that session has no row for it.
 */
export function flowSessions(rows) {
  const bySession = new Map();
  for (const row of rows ?? []) {
    const session = String(row?.session_date ?? "");
    if (!CATEGORIES.includes(row?.category) || !/^\d{4}-\d{2}-\d{2}$/.test(session)) continue;
    const entry = bySession.get(session) ?? { session, FII: null, DII: null };
    entry[row.category] = { buy: num(row.buy_value), sell: num(row.sell_value), net: num(row.net_value) };
    bySession.set(session, entry);
  }
  return [...bySession.values()].sort((a, b) => (a.session < b.session ? -1 : 1));
}

/**
 * One category's net over the last `count` sessions, and how many sessions
 * that sum actually covers; `net` is null when none of them reported it, so a
 * missing day never reads as zero.
 */
export function netOver(sessions, category, count) {
  const recent = sessions.slice(-count);
  const nets = recent.map((entry) => entry[category]?.net).filter((value) => value !== null && value !== undefined);
  return { net: nets.length ? nets.reduce((sum, value) => sum + value, 0) : null, sessions: nets.length };
}
