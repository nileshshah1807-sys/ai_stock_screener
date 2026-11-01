/**
 * US quarterly filings in the shape workers/financial_statements stores them
 * (`quarterly_filings`, market 'US': one consolidated row per company and
 * fiscal quarter, the last five, whole dollars, a line the vendor lacks null),
 * for developing the Results page before those rows exist. The figures are
 * invented. Read only when US_RESULTS_FIXTURES=1 (see lib/results.ts).
 */
import { monthsBefore } from "./financials.mjs";

// Fiscal quarter ends of the newest quarter: a 52-week year drifts off the month end.
const COMPANIES = [
  { symbol: "AAPL", company: "Apple Inc.", ends: ["2026-09-26", "2026-06-27", "2026-03-28", "2025-12-27", "2025-09-27"], revenue: 94e9, npm: 0.24, growth: 0.06, shares: 15.3e9, seen: "2026-10-30T21:10:00Z" },
  { symbol: "MSFT", company: "Microsoft Corporation", ends: [0, 3, 6, 9, 12], revenue: 65e9, npm: 0.36, growth: 0.15, shares: 7.43e9, seen: "2026-10-29T22:40:00Z" },
  { symbol: "NVDA", company: "NVIDIA Corporation", ends: ["2026-10-25", "2026-07-26", "2026-04-26", "2026-01-25", "2025-10-26"], revenue: 44e9, npm: 0.5, growth: 0.62, shares: 24.5e9, seen: "2026-10-30T09:20:00Z" },
  { symbol: "ORCL", company: "Oracle Corporation", ends: ["2026-08-31", "2026-05-31", "2026-02-28", "2025-11-30", "2025-08-31"], revenue: 14.2e9, npm: 0.2, growth: 0.09, shares: 2.8e9, seen: "2026-10-29T14:05:00Z" },
  { symbol: "NKE", company: "NIKE, Inc.", ends: ["2026-08-31", "2026-05-31", "2026-02-28", "2025-11-30", "2025-08-31"], revenue: 11.6e9, npm: 0.09, growth: -0.04, shares: 1.5e9, seen: "2026-10-30T20:15:00Z" },
  { symbol: "JPM", company: "JPMorgan Chase & Co.", ends: [0, 3, 6, 9, 12], revenue: 43e9, npm: 0.3, growth: 0.07, shares: 2.8e9, seen: "2026-10-28T11:30:00Z" },
  { symbol: "KO", company: "The Coca-Cola Company", ends: [0, 3, 6, 9, 12], revenue: 12.4e9, npm: 0.27, growth: 0.03, shares: 4.3e9, seen: "2026-10-28T10:00:00Z" },
  { symbol: "AMZN", company: "Amazon.com, Inc.", ends: [0, 3, 6, 9, 12], revenue: 155e9, npm: 0.09, growth: 0.11, shares: 10.7e9, seen: "2026-10-30T22:20:00Z", noEps: true },
  { symbol: "RIVN", company: "Rivian Automotive, Inc.", ends: [0, 3, 6, 9, 12], revenue: 1.4e9, npm: -0.6, growth: 0.2, shares: 1.2e9, seen: "2026-10-30T13:45:00Z" },
  { symbol: "COST", company: "Costco Wholesale Corporation", ends: ["2026-08-30", "2026-05-10", "2026-02-15", "2025-11-23", "2025-08-31"], revenue: 85e9, npm: 0.03, growth: 0.07, shares: 0.44e9, seen: "2026-10-29T21:30:00Z" },
];

/** The stored rows, newest quarter first within a company. `firstSeen` stands in for older quarters. */
export function fixtureFilings() {
  const rows = [];
  for (const spec of COMPANIES) {
    const ends = spec.ends.map((end) => (typeof end === "number" ? monthsBefore("2026-09-30", end) : end));
    ends.forEach((period_end, index) => {
      // Growth compounds backwards from the newest quarter; the year-ago quarter is four back.
      const revenue = Math.round(spec.revenue / (1 + spec.growth) ** (index / 4));
      const netProfit = Math.round(revenue * spec.npm);
      const pbt = Math.round(netProfit / (netProfit > 0 ? 0.82 : 1));
      const interest = Math.round(revenue * 0.01);
      const depreciation = Math.round(revenue * 0.03);
      rows.push({
        market: "US",
        symbol: spec.symbol,
        company: spec.company,
        period_end,
        is_consolidated: true,
        // Only the newest quarter has a real first sighting; older ones carry the day they were first stored.
        announced_at: index === 0 ? spec.seen : "2026-10-27T06:00:00Z",
        filed_at: null,
        document_url: "",
        viewer_url: null,
        lines: {
          revenue,
          net_profit: netProfit,
          pat: netProfit,
          pbt,
          tax: pbt - netProfit,
          interest,
          depreciation,
          operating_profit: pbt + interest + depreciation,
          eps: spec.noEps ? null : Number((netProfit / spec.shares).toFixed(2)),
        },
      });
    });
  }
  return rows;
}
