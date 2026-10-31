import type { Metadata } from "next";

import { PageTitle } from "@/components/page-title";
import { EventFilterBar } from "@/components/filters/event-filter-bar";
import { AnalysisChart } from "@/components/results/analysis-chart";
import { QuarterPicker } from "@/components/results/quarter-picker";
import { intersectSymbols } from "@/lib/event-filters.mjs";
import { loadFeedFilters } from "@/lib/feed-filters";
import { monthsBefore } from "@/lib/financials.mjs";
import { formatInteger } from "@/lib/format";
import { marketFromSlug } from "@/lib/markets";
import { getIndexDirectory, getIndexMembers } from "@/lib/queries";
import { getQuarterLines } from "@/lib/results";
import {
  ANALYSIS_LINES,
  ANALYSIS_SPANS,
  chosenSpan,
  formatChange,
  quarterEnds,
  quarterLabel,
  quarterMedians,
} from "@/lib/results.mjs";

export const metadata: Metadata = { title: "Results analysis" };
export const dynamic = "force-dynamic";

const TIME_ZONE = "Asia/Kolkata";
const SERIES_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

/**
 * How the quarters compare: for each of the latest 4, 6 or 8, the median
 * year-on-year growth in revenue, operating profit and PAT across the
 * companies that reported, with how many reported.
 *
 * Every rate is the one the company's Results card prints, from its stored
 * filings (`quarterMedians`), over the same shared filter bar as the card list
 * -- industry, watchlist and the rules, including the default market-cap
 * floor -- plus an index. Only the filings of the quarters shown and the
 * year-ago ones are read, and only their three lines.
 *
 * NSE only, like Results.
 */
export default async function ResultsAnalysisPage({
  params,
  searchParams,
}: PageProps<"/[market]/results/analysis">) {
  const market = marketFromSlug((await params).market)!;
  const query = await searchParams;

  if (market.code !== "NSE") {
    return (
      <div className="space-y-4 px-4 py-5 sm:px-6">
        <h1 className="text-title font-semibold">Results analysis</h1>
        <div className="panel px-5 py-10 text-center">
          <p className="text-sm font-medium">NSE only</p>
        </div>
      </div>
    );
  }

  const today = new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE }).format(new Date());
  const span = chosenSpan(query.n);
  const quarters = quarterEnds(today, span);
  const periods = [...new Set(quarters.flatMap((end) => [end, monthsBefore(end, 12)]))];

  const [feed, indices] = await Promise.all([
    loadFeedFilters(market.code, query, { defaultScope: "all" }),
    getIndexDirectory(market.code),
  ]);
  const indexParam = Array.isArray(query.index) ? query.index[0] : query.index;
  const index = indices.find((item) => item.slug === indexParam && item.members);
  const members = index ? await getIndexMembers(market.code, index.name) : null;
  const scope = intersectSymbols(
    feed.symbols ? new Set(feed.symbols) : null,
    members ? members.map((member) => member.symbol) : null,
  );

  const lines = scope && scope.size === 0 ? [] : await getQuarterLines(market.code, periods, scope ? [...scope] : null);
  const rows = quarterMedians(lines, quarters, scope);
  const reported = rows.reduce((sum, row) => sum + row.results, 0);

  const series = ANALYSIS_LINES.map((line, position) => ({ ...line, color: SERIES_COLORS[position] }));
  const columns = rows.map((row) => ({
    label: quarterLabel(row.quarter),
    results: row.results,
    values: ANALYSIS_LINES.map((line) => row.series[line.key]),
  }));

  return (
    <div className="space-y-4 px-4 py-5 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageTitle
          title="Results analysis"
          info={
            <>
              <p>
                The median year-on-year growth of the companies that reported each quarter, from their own
                filings with the exchange.
              </p>
              <p>
                A result is a company that filed the quarter. Each median is over the companies with a
                growth rate for that line, the number in brackets: there is no rate off a loss or without a
                filing for the same quarter a year earlier, and the exchange&rsquo;s index of filings begins
                in April 2025, so earlier quarters have few. A company counts on the basis its Results card
                opens on. Operating profit is profit before tax with interest and depreciation added back.
              </p>
            </>
          }
        />
        <div className="flex flex-wrap gap-2">
          <QuarterPicker
            param="index"
            name="Index"
            value={index?.slug ?? ""}
            options={[
              { value: "", label: "All companies" },
              ...indices.filter((item) => item.members).map((item) => ({ value: item.slug, label: item.name })),
            ]}
          />
          <QuarterPicker
            param="n"
            name="Quarters"
            value={String(span)}
            options={[
              { value: "6", label: "6 quarters" },
              ...ANALYSIS_SPANS.filter((count) => count !== 6).map((count) => ({
                value: String(count),
                label: `${count} quarters`,
              })),
            ]}
          />
        </div>
      </div>

      <EventFilterBar {...feed.bar} />

      {reported ? (
        <div className="space-y-6">
          <div className="panel p-4">
            <AnalysisChart columns={columns} series={series} />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[32rem] text-sm">
              <caption className="sr-only">Median year-on-year growth by quarter</caption>
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th scope="col" className="py-2 pr-4 font-medium">Quarter</th>
                  <th scope="col" className="py-2 pr-4 text-right font-medium">Results</th>
                  {ANALYSIS_LINES.map((line) => (
                    <th key={line.key} scope="col" className="py-2 pr-4 text-right font-medium">
                      {line.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...rows].reverse().map((row) => (
                  <tr key={row.quarter} className="border-b last:border-0">
                    <th scope="row" className="py-2 pr-4 text-left font-medium">{quarterLabel(row.quarter)}</th>
                    <td className="tabular py-2 pr-4 text-right">{formatInteger(row.results)}</td>
                    {ANALYSIS_LINES.map((line) => {
                      const cell = row.series[line.key];
                      return (
                        <td key={line.key} className="tabular py-2 pr-4 text-right">
                          {formatChange(cell.median) ?? "–"}
                          <span className="ml-1 text-xs text-muted-foreground">
                            {cell.n ? `(${formatInteger(cell.n)})` : ""}
                          </span>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="panel px-5 py-10 text-center">
          <p className="text-sm font-medium">No results for these filters.</p>
        </div>
      )}
    </div>
  );
}
