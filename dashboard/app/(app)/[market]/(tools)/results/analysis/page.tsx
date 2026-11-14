import type { Metadata } from "next";

import { PageTitle } from "@/components/page-title";
import { EventFilterBar } from "@/components/filters/event-filter-bar";
import { AnalysisChart } from "@/components/results/analysis-chart";
import { AutoRefresh } from "@/components/results/auto-refresh";
import { QuarterPicker } from "@/components/results/quarter-picker";
import { SpanControl } from "@/components/results/span-control";
import { intersectSymbols } from "@/lib/event-filters.mjs";
import { loadFeedFilters } from "@/lib/feed-filters";
import { monthsBefore } from "@/lib/financials.mjs";
import { formatInteger } from "@/lib/format";
import { cn } from "@/lib/utils";
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
  quarterWindow,
} from "@/lib/results.mjs";

export const metadata: Metadata = { title: "Results analysis" };
export const dynamic = "force-dynamic";


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
 * NSE finds a company's quarter by its exact quarter end; the US by the calendar
 * quarter's window, as its companies keep their own fiscal calendars.
 */
export default async function ResultsAnalysisPage({
  params,
  searchParams,
}: PageProps<"/[market]/results/analysis">) {
  const market = marketFromSlug((await params).market)!;
  const query = await searchParams;

  const today = new Intl.DateTimeFormat("en-CA", { timeZone: market.timezone }).format(new Date());
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
  const us = market.code === "US";
  const rows = quarterMedians(lines, quarters, scope, us);
  const reported = rows.reduce((sum, row) => sum + row.results, 0);

  const newest = rows[rows.length - 1];
  // The newest quarter's results are still arriving until its window closes.
  const inProgress = !!newest && today <= quarterWindow(newest.quarter).through;
  const points = (key: string) =>
    rows.map((row) => ({ label: quarterLabel(row.quarter), median: row.series[key].median, n: row.series[key].n }));

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
          <SpanControl
            param="n"
            name="Quarters"
            value={String(span)}
            defaultValue="6"
            options={ANALYSIS_SPANS.map((count) => ({ value: String(count), label: String(count) }))}
          />
        </div>
      </div>

      <EventFilterBar {...feed.bar} />
      {/* As on the card list: re-read while results arrive. The whole-market read is a 10-minute
          stale-while-revalidate cache, so a new filing shows by the second refresh, no reload. */}
      {inProgress ? <AutoRefresh /> : null}

      {reported && newest ? (
        <div className="space-y-3">
          <div className="panel grid divide-y sm:grid-cols-3 sm:divide-x sm:divide-y-0">
            {ANALYSIS_LINES.map((line) => {
              const cell = newest.series[line.key];
              const value = cell.median;
              return (
                <div key={line.key} className="p-4">
                  <p className="text-xs text-muted-foreground">
                    {line.label}, {quarterLabel(newest.quarter)}
                    {inProgress ? (
                      <span className="ml-1.5 rounded-full border px-2 py-px text-[11px]">season in progress</span>
                    ) : null}
                  </p>
                  <p
                    className={cn(
                      "tabular mt-0.5 text-[26px] font-semibold tracking-[-0.02em]",
                      value == null || value === 0 ? "text-muted-foreground" : value > 0 ? "text-positive" : "text-negative",
                    )}
                  >
                    {formatChange(value) ?? "–"}
                    {cell.n ? (
                      <small className="ml-1 text-[13px] font-medium tracking-normal text-muted-foreground">
                        median of {formatInteger(cell.n)}
                      </small>
                    ) : null}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {formatInteger(newest.results)} {inProgress ? "results so far" : "results"}
                  </p>
                </div>
              );
            })}
          </div>
          <div className="grid gap-3 lg:grid-cols-3">
            {ANALYSIS_LINES.map((line) => (
              <section key={line.key} className="panel p-4">
                <h2 className="mb-2 text-[13px] font-semibold">{line.label}</h2>
                <AnalysisChart title={line.label} points={points(line.key)} inProgress={inProgress} />
              </section>
            ))}
          </div>
          <div className="panel overflow-x-auto">
            <table className="tabular w-full text-sm">
              <caption className="sr-only">Median year-on-year growth by quarter</caption>
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th scope="col" className="px-3 py-2 text-left font-medium sm:px-4">Quarter</th>
                  <th scope="col" className="hidden px-4 py-2 text-right font-medium sm:table-cell">Results</th>
                  {ANALYSIS_LINES.map((line) => (
                    <th key={line.key} scope="col" className="px-2 py-2 text-right font-medium sm:px-4">
                      {line.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y">
                {[...rows].reverse().map((row, position) => (
                  <tr key={row.quarter}>
                    <th scope="row" className="whitespace-nowrap px-3 py-2 text-left font-semibold sm:px-4">
                      {quarterLabel(row.quarter)}
                      {position === 0 && inProgress ? (
                        <span className="ml-1.5 hidden rounded-full border px-2 py-px text-[11px] font-normal text-muted-foreground sm:inline">
                          in progress
                        </span>
                      ) : null}
                    </th>
                    <td className="hidden px-4 py-2 text-right sm:table-cell">{formatInteger(row.results)}</td>
                    {ANALYSIS_LINES.map((line) => {
                      const cell = row.series[line.key];
                      return (
                        <td
                          key={line.key}
                          className={cn(
                            "whitespace-nowrap px-2 py-2 text-right sm:px-4",
                            cell.median == null || cell.median === 0
                              ? "text-muted-foreground"
                              : cell.median > 0
                                ? "text-positive"
                                : "text-negative",
                          )}
                        >
                          {formatChange(cell.median) ?? "–"}
                          <span className="ml-1 hidden text-[11px] text-muted-foreground sm:inline">
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
          <p className="max-w-prose px-0.5 text-xs leading-relaxed text-muted-foreground">
            {us
              ? "A result is a company whose fiscal quarter ends in the calendar quarter\u2019s window (about 45 days before to 45 days after its end). We hold five quarters per company, so earlier quarters have no year-ago base and show a dash."
              : "A result is a company that filed the quarter; each median is over the companies with a growth rate, in brackets. There is no rate off a loss or without the same quarter a year earlier, and the exchange\u2019s index of filings begins in April 2025, so earlier quarters show a dash."}
          </p>
        </div>
      ) : (
        <div className="panel px-5 py-10 text-center">
          <p className="text-sm font-medium">No results for these filters.</p>
        </div>
      )}
    </div>
  );
}
