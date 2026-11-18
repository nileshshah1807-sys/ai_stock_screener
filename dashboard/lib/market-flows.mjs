/**
 * The NSE Market page's flows card, worked out from the rows
 * workers/market_flows.py writes (tables fii_dii_flows and participant_oi, and
 * the R2 objects live/NSE/fii-dii-flows.json and participant-oi.json):
 * `{ session_date, category, net_value, ... }`, values in rupees crore, and
 * `{ session_date, category, future_index_long, future_index_short, ... }`,
 * in contracts. Display only: nothing scores on it.
 */

export const FLOW_BARS = 20;
export const OI_CATEGORIES = ["Client", "FII", "DII", "Pro"];

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
 * Index-futures positioning on the latest session: per participant, long and short
 * contracts, net (long - short) and the long share of their open positions.
 * null when there are no rows.
 */
export function indexFuturesPositioning(rows) {
  const latest = (rows ?? []).reduce((max, row) => (row?.session_date > max ? row.session_date : max), "");
  if (!latest) return null;
  const today = new Map(rows.filter((row) => row.session_date === latest).map((row) => [row.category, row]));
  const participants = OI_CATEGORIES.filter((c) => today.has(c)).map((category) => {
    const long = Number(today.get(category).future_index_long);
    const short = Number(today.get(category).future_index_short);
    return { category, long, short, net: long - short, longShare: long + short ? long / (long + short) : null };
  });
  return { date: latest, participants };
}
