/**
 * Rows as the reader hands them on (the table's columns it reads, plus the
 * `company` it adds from the latest run), one per stock, for developing the UI
 * before the table exists. Read only when UPCOMING_FIXTURES=1 (see
 * lib/upcoming.ts); the volumes follow the exchange's notices: results peak
 * near 200 a day, and about one call in four names no time.
 */
const RESULTS_PER_DAY = [53, 0, 0, 133, 179, 205, 213, 140, 60, 0, 0, 22, 9];
const CALLS_PER_DAY = [14, 0, 0, 96, 118, 104, 90, 61, 40, 0, 0, 12, 0];
const HOURS = [10, 11, 12, 14, 15, 16, 17];
const REAL = ["TCS", "RELIANCE", "INFY", "HDFCBANK", "ITC"];

const day = (today, offset) =>
  new Date(Date.parse(`${today}T00:00:00Z`) + offset * 86_400_000).toISOString().slice(0, 10);

export function fixtureRows(today) {
  const rows = new Map();
  const row = (symbol) => {
    if (!rows.has(symbol)) {
      rows.set(symbol, { symbol, company: `${symbol} Limited`, next_result_date: null, next_call_at: null, next_call_date: null });
    }
    return rows.get(symbol);
  };
  RESULTS_PER_DAY.forEach((count, offset) => {
    for (let i = 0; i < count; i += 1) {
      const symbol = offset === 4 && i < REAL.length ? REAL[i] : `RES${offset}X${String(i).padStart(3, "0")}`;
      row(symbol).next_result_date = day(today, offset);
    }
  });
  CALLS_PER_DAY.forEach((count, offset) => {
    for (let i = 0; i < count; i += 1) {
      const entry = row(`CALL${offset}X${String(i).padStart(3, "0")}`);
      const date = day(today, offset);
      if (i % 4 === 3) entry.next_call_date = date;
      else entry.next_call_at = `${date}T${String(HOURS[i % HOURS.length]).padStart(2, "0")}:${i % 2 ? "30" : "00"}:00+05:30`;
    }
  });
  return [...rows.values()];
}

const US_COMPANIES = [
  ["NFLX", "Netflix, Inc."], ["TSLA", "Tesla, Inc."], ["GOOGL", "Alphabet Inc."], ["META", "Meta Platforms, Inc."],
  ["V", "Visa Inc."], ["MA", "Mastercard Incorporated"], ["PG", "The Procter & Gamble Company"], ["HD", "The Home Depot, Inc."],
  ["WMT", "Walmart Inc."], ["CRM", "Salesforce, Inc."], ["DIS", "The Walt Disney Company"], ["PFE", "Pfizer Inc."],
  ["INTC", "Intel Corporation"], ["AMD", "Advanced Micro Devices, Inc."], ["UBER", "Uber Technologies, Inc."], ["PYPL", "PayPal Holdings, Inc."],
  ["SBUX", "Starbucks Corporation"], ["T", "AT&T Inc."], ["CVX", "Chevron Corporation"], ["BA", "The Boeing Company"],
  ["LLY", "Eli Lilly and Company"], ["MRK", "Merck & Co., Inc."], ["CAT", "Caterpillar Inc."], ["GE", "GE Aerospace"],
  ["SHOP", "Shopify Inc."], ["SNAP", "Snap Inc."], ["PLTR", "Palantir Technologies Inc."], ["ABNB", "Airbnb, Inc."],
  ["COIN", "Coinbase Global, Inc."], ["DASH", "DoorDash, Inc."], ["F", "Ford Motor Company"], ["GM", "General Motors Company"],
];
const US_PER_DAY = [6, 4, 0, 0, 5, 7, 6, 2, 0, 0, 1, 1];

/** Rows for the US, one per stock: result dates only, as Alpha Vantage's calendar gives them. */
export function usFixtureRows(today) {
  const rows = [];
  let next = 0;
  US_PER_DAY.forEach((count, offset) => {
    for (let i = 0; i < count && next < US_COMPANIES.length; i += 1, next += 1) {
      const [symbol, company] = US_COMPANIES[next];
      rows.push({ symbol, company, next_result_date: day(today, offset), next_call_at: null, next_call_date: null });
    }
  });
  return rows;
}
