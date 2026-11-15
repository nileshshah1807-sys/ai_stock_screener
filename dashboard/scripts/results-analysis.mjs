// The Results analysis page's per-company rates, worked out by the page's own
// code (lib/results.mjs) so there is no second copy of the math.
// workers/results_analysis.py pipes {market, today, filings} in and stores what
// this prints as live/{MARKET}/results-analysis.json.
import { monthsBefore } from "../lib/financials.mjs";
import { ANALYSIS_SPANS, quarterEnds, quarterRates, quarterWindow } from "../lib/results.mjs";

/**
 * The filings the page would read for `quarters` (lib/results.ts inQuarters):
 * NSE by exact quarter end, the US by each quarter's window.
 */
export function analysisInput(filings, quarters, windowed) {
  const ends = [...new Set(quarters.flatMap((end) => [end, monthsBefore(end, 12)]))];
  if (!windowed) {
    const wanted = new Set(ends);
    return filings.filter((filing) => wanted.has(filing.period_end));
  }
  const windows = ends.map(quarterWindow);
  return filings.filter((filing) =>
    windows.some(({ after, through }) => filing.period_end > after && filing.period_end <= through),
  );
}

/** The stored object: every quarter the page offers, oldest first. */
export function resultsAnalysis({ market, today, filings }) {
  const quarters = quarterEnds(today, Math.max(...ANALYSIS_SPANS));
  const windowed = market === "US";
  const rates = quarterRates(analysisInput(filings, quarters, windowed), quarters, windowed);
  // Each company once, then by its place; rates to 2 decimals (a median moves by under 0.01 point).
  const symbols = [...new Set(rates.flatMap((entry) => entry.companies.map(([symbol]) => symbol)))].sort();
  const place = new Map(symbols.map((symbol, index) => [symbol, index]));
  const round = (rate) => (rate === null ? null : Math.round(rate * 100) / 100);
  return {
    market,
    today,
    symbols,
    rows: rates.map(({ quarter, companies }) => ({
      quarter,
      companies: companies.map(([symbol, ...lines]) => [place.get(symbol), ...lines.map(round)]),
    })),
  };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  process.stdout.write(JSON.stringify(resultsAnalysis(JSON.parse(Buffer.concat(chunks).toString("utf8")))));
}
