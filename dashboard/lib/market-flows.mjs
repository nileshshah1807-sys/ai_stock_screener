/**
 * The NSE Market page's flows card, worked out from the rows
 * workers/market_flows.py writes (table fii_dii_flows and
 * the R2 object live/NSE/fii-dii-flows.json):
 * `{ session_date, category, net_value, ... }`, values in rupees crore, plus the
 * object's calendar-year totals. Display only: nothing scores on it.
 */

export const FLOW_BARS = 20;

const net = (row) => (typeof row?.net_value === "number" && Number.isFinite(row.net_value) ? row.net_value : null);
const sum = (values) => (values.some((v) => v !== null) ? values.reduce((a, v) => a + (v ?? 0), 0) : null);

/**
 * Sessions oldest first, each { date, fii, dii } (null where a side was not reported);
 * the last FLOW_BARS of them as bars; and 5-session and month-to-date net per side.
 * null when there are no rows.
 */
export function flowSummary(rows) {
  const byDate = new Map();
  for (const row of rows ?? []) {
    if (row?.category !== "FII" && row?.category !== "DII") continue;
    const session = byDate.get(row.session_date) ?? { date: row.session_date, fii: null, dii: null };
    session[row.category === "FII" ? "fii" : "dii"] = net(row);
    byDate.set(row.session_date, session);
  }
  const sessions = [...byDate.values()].sort((a, b) => (a.date < b.date ? -1 : 1));
  if (!sessions.length) return null;
  const date = sessions.at(-1).date;
  const last5 = sessions.slice(-5);
  const month = sessions.filter((s) => s.date.slice(0, 7) === date.slice(0, 7));
  return {
    date,
    bars: sessions.slice(-FLOW_BARS),
    fiveDay: { sessions: last5.length, fii: sum(last5.map((s) => s.fii)), dii: sum(last5.map((s) => s.dii)) },
    monthToDate: { sessions: month.length, fii: sum(month.map((s) => s.fii)), dii: sum(month.map((s) => s.dii)) },
  };
}

/**
 * Calendar-year totals from the object's `years` (storage/dashboard_repository.py,
 * fii_dii_years): newest first, each { year, fii, dii, sessions }, nets in crore,
 * null where a side was not reported. null when there are none.
 */
export function flowYears(years) {
  const byYear = new Map();
  for (const row of Array.isArray(years) ? years : []) {
    if ((row?.category !== "FII" && row?.category !== "DII") || !Number.isInteger(row.year)) continue;
    const entry = byYear.get(row.year) ?? { year: row.year, fii: null, dii: null, sessions: 0 };
    entry[row.category === "FII" ? "fii" : "dii"] = net(row);
    entry.sessions = Math.max(entry.sessions, Number(row.sessions) || 0);
    byYear.set(row.year, entry);
  }
  const rows = [...byYear.values()].sort((a, b) => b.year - a.year);
  return rows.length ? rows : null;
}
