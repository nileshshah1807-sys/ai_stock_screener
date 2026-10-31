import { notFound } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { DEFAULT_MARKET } from "@/lib/markets";
import { RatingBadge } from "@/components/rating-badge";
import { SummaryTiles } from "@/components/summary-tiles";
import { ScreenerTable } from "@/components/screener/screener-table";
import { CallOutlook } from "@/components/stock/call-outlook";
import { DecisionScore } from "@/components/stock/decision-score";
import { FieldList, Panel } from "@/components/stock/field-list";
import { ScoreWaterfall } from "@/components/stock/score-waterfall";
import { PayloadExplorer } from "@/components/stock/payload-explorer";
import { Financials } from "@/components/stock/financials";
import { StockTabs } from "@/components/stock/stock-tabs";
import { NotRatedRows } from "@/components/screener/not-rated-rows";
import { NewListingView } from "@/components/stock/new-listing-view";
import { Suspense } from "react";
import { ActiveFilters } from "@/components/screener/active-filters";
import { EventFilterBar } from "@/components/filters/event-filter-bar";
import { AnalysisChart } from "@/components/results/analysis-chart";
import { QuarterPicker } from "@/components/results/quarter-picker";
import { UpcomingResultChip } from "@/components/upcoming/upcoming-result-chip";
import { UpcomingButton, UpcomingProvider } from "@/components/upcoming/upcoming-sheet";
import { NextConcallTile, ResultsLinedUpTile } from "@/components/upcoming/upcoming-tiles";
import { fixtureRows } from "@/lib/upcoming-fixtures.mjs";
import { eventsFromRows, upcomingSummary } from "@/lib/upcoming.mjs";
import { ExportLink } from "@/components/screener/export-link";
import { FilterBar } from "@/components/screener/filter-bar";
import { SavedViews } from "@/components/screener/saved-views";
import { StockSearch } from "@/components/screener/stock-search";
import { ViewOptions } from "@/components/screener/view-options";
import { ThemeToggle } from "@/components/theme-toggle";
import { RATINGS } from "@/lib/types";

import {
  previewDetailRow,
  previewFinancials,
  previewListingSeries,
  previewListingSessions,
  previewNewListings,
  previewNotifications,
  previewRows,
  previewRun,
} from "./fixtures";

/**
 * Development-only design preview.
 *
 * The application is gated behind Supabase auth, so there is no way to see the
 * real surfaces without a live session and a published run. This route renders
 * the same components against fixture data so the design work can be checked
 * in a browser.
 *
 * It lives under /auth because proxy.ts already treats that prefix as public,
 * which means adding it required no change to the authentication boundary. The
 * notFound() below is the actual guard: NODE_ENV is inlined at build time, so
 * in a production build this file compiles to a route that always 404s.
 */
export const dynamic = "force-static";

function UpcomingPreview() {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
  const rows = fixtureRows(today);
  const results = eventsFromRows(rows, "results", today) as import("@/lib/upcoming").UpcomingEvent[];
  const calls = eventsFromRows(rows, "call", today) as import("@/lib/upcoming").UpcomingEvent[];
  const next = upcomingSummary(calls, today).next;
  const lists = [{ id: "a", name: "Core", symbols: results.slice(0, 20).map((row) => row.symbol) }];
  return (
    <div className="space-y-3">
      <UpcomingProvider kind="results" rows={results} today={today} lists={lists}>
        <div className="flex flex-wrap items-start gap-3">
          <ResultsLinedUpTile lined={results.length} declared={612} soonest={results} logos={new Map()} />
          <UpcomingButton />
        </div>
      </UpcomingProvider>
      <UpcomingProvider kind="call" rows={calls} today={today} lists={lists}>
        <div className="flex flex-wrap items-start gap-3">
          {next ? <NextConcallTile next={next} today={today} logoDomain={null} /> : null}
          <UpcomingButton />
        </div>
      </UpcomingProvider>
      <UpcomingResultChip date={results[results.length - 1].event_date} />
    </div>
  );
}

export default function PreviewPage() {
  if (process.env.NODE_ENV !== "development") notFound();

  return (
    // Wrapped in the real AppShell so the top bar, the tabs, the brand mark,
    // the freshness banner and the footer are all exercised too -- those are
    // the surfaces a component-only preview would silently skip.
    <AppShell
      run={previewRun}
      viewer={{ id: "preview", email: "preview@localhost", role: "viewer" }}
      market={DEFAULT_MARKET}
      notifications={Promise.resolve(previewNotifications)}
    >
      <div className="flex flex-col gap-8 px-4 py-8 sm:px-8">
        <header className="flex items-center justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-wider text-muted-foreground">
              Development preview
            </p>
            <h1 className="text-title">Design system check</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Fixture data. Toggle the theme to verify both palettes.
            </p>
          </div>
          <ThemeToggle />
        </header>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Type scale</h2>
          <div className="panel flex flex-col gap-4 p-6">
            <p className="numeral text-display">1,847</p>
            <p className="text-title">Market research overview</p>
            <p className="text-heading">Score Distribution</p>
            <p className="text-lead">Evidence summary lead paragraph</p>
            <p className="text-sm">
              Body copy at 14px, the working size across the interface.
            </p>
            <p className="text-xs text-muted-foreground">
              Small label at 12px for axes and metadata.
            </p>
            <p className="text-micro uppercase tracking-wider text-muted-foreground">
              Micro chip label at 10px
            </p>
            <p className="tabular font-mono text-sm">
              0123456789 · mono tabular figures for the grid
            </p>
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Rating ramp</h2>
          <div className="panel flex flex-wrap items-center gap-3 p-6">
            {RATINGS.map((rating) => (
              <RatingBadge key={rating} rating={rating} size="md" />
            ))}
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">KPI band</h2>
          <SummaryTiles run={previewRun} market={DEFAULT_MARKET} />
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Screener grid</h2>
          <ScreenerTable
            rows={previewRows}
            params={new URLSearchParams()}
            sort="investment_rank"
            dir="asc"
          />
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <Panel
            title="Decision score"
            description="The published score against the 0-100 range it is rated on. Ticks mark the REDUCE / HOLD / BUY / STRONG BUY boundaries."
          >
            <DecisionScore
              score={previewDetailRow.decision_score}
              rating={previewDetailRow.rating}
            />
          </Panel>

          <Panel
            title="Price and size"
            description="Field list inside the panel treatment."
          >
            <FieldList
              columns={2}
              fields={[
                { label: "Price", value: "₹391.15" },
                { label: "Market cap", value: "₹1,452 Cr" },
                { label: "1M", value: "+4.2%", tone: "positive" },
                { label: "3M", value: "-1.8%", tone: "negative" },
                { label: "Coverage", value: "92%", tone: "caution" },
                { label: "Liquidity", value: "A", tone: "muted" },
              ]}
            />
          </Panel>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Score waterfall</h2>
          <Panel title="How this score was produced">
            <ScoreWaterfall row={previewDetailRow} />
          </Panel>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Call outlook</h2>
          <CallOutlook payload={previewDetailRow.payload} />
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Results analysis</h2>
          <Suspense>
            <div className="flex gap-2">
              <QuarterPicker param="index" name="Index" value="" options={[{ value: "", label: "All companies" }]} />
              <QuarterPicker
                param="n"
                name="Quarters"
                value="6"
                options={[{ value: "6", label: "6 quarters" }, { value: "4", label: "4 quarters" }]}
              />
            </div>
          </Suspense>
          <div className="panel p-4">
            <AnalysisChart
              series={[
                { key: "revenue", label: "Revenue", color: "var(--series-1)" },
                { key: "operating_profit", label: "Operating profit", color: "var(--series-2)" },
                { key: "net_profit", label: "PAT", color: "var(--series-3)" },
              ]}
              columns={[
                ["Jun 2025", 227, [9.1, 13.8, 13]],
                ["Sep 2025", 231, [11.1, 12.2, 12.9]],
                ["Dec 2025", 243, [13, 19.7, -6.4]],
                ["Mar 2026", 246, [15.8, 23.2, 29.5]],
                ["Jun 2026", 251, [20.1, 25.1, 28.5]],
                ["Sep 2026", 54, [22.4, null, 41]],
              ].map(([label, results, medians]) => ({
                label: label as string,
                results: results as number,
                values: (medians as (number | null)[]).map((median) => ({ median, n: median === null ? 0 : (results as number) - 12 })),
              }))}
            />
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Upcoming events</h2>
          <UpcomingPreview />
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Results filters (with growth)</h2>
          <Suspense>
            <EventFilterBar
              market="NSE"
              defaultScope="all"
              growth
              filters={{
                rules: [
                  { metric: "mcap", op: "gte", value: 1000 },
                  { metric: "revyoy", op: "gte", value: 15 },
                  { metric: "patqoq", op: "gte", value: 0 },
                ],
                industries: [],
                lists: [],
                facets: {},
              }}
              industries={[{ value: "Auto Parts", label: "Auto Parts", count: 84 }]}
              watchlists={[{ value: "core", label: "Core holdings", count: 14 }]}
            />
          </Suspense>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Feed filters</h2>
          {/* The bar above Notifications and Concalls, opened on the default
              view. A static page cannot re-render for a new URL, so a choice
              made here shows in the address bar and then settles back. */}
          <Suspense>
            <EventFilterBar
              market="NSE"
              defaultScope="all"
              filters={{
                rules: [{ metric: "mcap", op: "gte", value: 1000 }],
                industries: [],
                lists: [],
                facets: {},
              }}
              industries={[
                { value: "Auto Parts", label: "Auto Parts", count: 84 },
                { value: "Banks - Regional", label: "Banks - Regional", count: 37 },
                { value: "Specialty Chemicals", label: "Specialty Chemicals", count: 112 },
              ]}
              watchlists={[
                { value: "core", label: "Core holdings", count: 14 },
                { value: "watch", label: "Results to watch", count: 31 },
              ]}
              facets={[
                {
                  param: "stance",
                  label: "Mgmt Sentiment",
                  options: [
                    { value: "bullish", label: "Bullish" },
                    { value: "optimistic", label: "Optimistic" },
                    { value: "neutral", label: "Neutral" },
                    { value: "cautious", label: "Cautious" },
                    { value: "bearish", label: "Bearish" },
                  ],
                },
              ]}
            />
          </Suspense>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Screener toolbar</h2>
          {/* Same structure as (screener)/layout.tsx. Suspense because these
              read the query string, which a static page only has on the client. */}
          <Suspense>
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex-1">
                  <FilterBar sectors={["Financials", "Information Technology", "Industrials"]} factorModel />
                </div>
                <ViewOptions factorModel />
                <StockSearch />
                <ExportLink />
              </div>
              <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
                <SavedViews factorModel />
                <ActiveFilters />
              </div>
            </div>
          </Suspense>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Grid tail: Not rated rows</h2>
          <NotRatedRows rows={previewNewListings} market={DEFAULT_MARKET} />
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">New listing, first session (no statements)</h2>
          <div className="panel overflow-hidden">
            <NewListingView
              listing={{ ...previewNewListings[0], symbol: "TONBO", company: "Tonbo Imaging Limited", sessions: 1, change_since_first_pct: null }}
              market={DEFAULT_MARKET}
              financials={{ ...previewFinancials, has_data: false, statements: {} as typeof previewFinancials.statements }}
              shareholding={null}
              watchlists={[]}
              watchlistMembership={[]}
              priceSeries={null}
              sessions={[]}
              priceTail={[]}
              asOf="2026-09-23"
              tab="financials"
            />
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">New listing stock page</h2>
          <div className="panel overflow-hidden">
            <NewListingView
              listing={{
                ...previewNewListings[3],
                // The series starts on the listing date, as a real listing's does.
                listed_on: previewListingSessions[0],
                last_close: 44.5,
                market_cap: 4475320500,
              }}
              market={DEFAULT_MARKET}
              financials={previewFinancials}
              shareholding={null}
              watchlists={[]}
              watchlistMembership={[]}
              priceSeries={previewListingSeries}
              sessions={previewListingSessions}
              priceTail={[]}
              asOf="2026-09-23"
              tab="overview"
            />
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Stock page tabs</h2>
          <StockTabs
            initial="overview"
            tabs={[
              { key: "overview", label: "Overview", content: <div className="panel p-6 text-sm">Overview content</div> },
              { key: "financials", label: "Financials", content: <div className="panel p-6 text-sm">Financials content</div> },
              { key: "audit", label: "Audit", content: <div className="panel p-6 text-sm">Audit content</div> },
            ]}
          />
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Financials</h2>
          <Panel
            title="Financials"
            description="Real TCS vendor output, including a quarter the source skips."
          >
            <Financials
              data={previewFinancials}
              market={DEFAULT_MARKET}
              symbol="TCS"
              asOf="2026-09-22"
            />
          </Panel>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Complete source record</h2>
          <Panel
            title="Complete source record"
            description="Must have no horizontal scrollbar, and figures must carry separators."
          >
            <PayloadExplorer payload={previewDetailRow.payload} />
          </Panel>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Every rating, as a ring</h2>
          <div className="grid gap-4 sm:grid-cols-3 xl:grid-cols-5">
            {[
              { score: 78.4, rating: "STRONG BUY" },
              { score: 68.5, rating: "BUY" },
              { score: 56.1, rating: "HOLD" },
              { score: 44.2, rating: "REDUCE" },
              { score: 31.7, rating: "SELL" },
            ].map((item) => (
              <div key={item.rating} className="panel p-5">
                <DecisionScore
                  score={item.score}
                  rating={item.rating}
                  caption={item.rating}
                />
              </div>
            ))}
          </div>
        </section>
      </div>
    </AppShell>
  );
}
