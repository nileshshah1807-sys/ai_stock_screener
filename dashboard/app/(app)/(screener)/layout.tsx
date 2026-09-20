import { SummaryTiles } from "@/components/summary-tiles";
import { ActiveFilters } from "@/components/screener/active-filters";
import { ExportLink } from "@/components/screener/export-link";
import { FilterBar } from "@/components/screener/filter-bar";
import { SavedViews } from "@/components/screener/saved-views";
import { StockSearch } from "@/components/screener/stock-search";
import { ViewOptions } from "@/components/screener/view-options";
import { investmentRankExplanation } from "@/lib/model-display.mjs";
import { getLatestRun, getSectors, runUsesFactorModel } from "@/lib/queries";
import { mark, trace } from "@/lib/trace";

/**
 * Screener chrome: summary tiles, filters, search and export.
 *
 * Everything here depends only on which run is published, never on the current
 * sort, filter or page. Keeping it in a layout is what makes those interactions
 * cheap -- layouts do not re-render on navigation, so clicking a column header
 * re-runs the grid query alone instead of also rebuilding the sector list and
 * the factor-model probe.
 *
 * FilterBar reads the query string through useSearchParams on the client, so it
 * still reflects the active filters despite living outside the page.
 */
export default async function ScreenerLayout({ children }: LayoutProps<"/">) {
  mark("(screener)/layout RENDERED");
  const run = await trace("  getLatestRun", () => getLatestRun());

  if (!run) return <>{children}</>;

  // The publisher records both of these on the run, so the common path costs
  // nothing beyond the manifest read that already happened. The fallbacks are
  // for runs published before those columns existed: getSectors reads one
  // column across the whole universe and runUsesFactorModel is a second probe,
  // together ~500ms and two round trips on every full page load.
  //
  // `??` rather than `||` for the flag, so a run that genuinely scored without
  // the factor model reads as false instead of triggering the fallback query.
  const [sectors, factorModel] = await Promise.all([
    run.sectors?.length
      ? run.sectors
      : trace("  getSectors (fallback)", () =>
          getSectors(run.run_date, run.row_count),
        ),
    run.factor_model_applied ??
      trace("  runUsesFactorModel (fallback)", () =>
        runUsesFactorModel(run.run_date),
      ),
  ]);

  return (
    <div className="space-y-4 px-4 py-5 sm:px-6">
      <SummaryTiles run={run} />

      {/*
        One chrome block at gap-2, not three siblings at the page's gap-4.
        Every row of chrome here is a row the grid does not get: the grid is
        bounded to the viewport so its header can stay pinned, which makes
        vertical space above it a direct trade against rows on screen.
      */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex-1">
            <FilterBar sectors={sectors} factorModel={factorModel} />
          </div>
          <ViewOptions factorModel={factorModel} />
          <StockSearch />
          <ExportLink />
        </div>

        {/* Views and the active-filter readout share a line rather than taking
            one each. Both are chip rows of unpredictable length, so they wrap
            independently when long and cost a single row when short -- which is
            the common case. */}
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
          <SavedViews factorModel={factorModel} />
          <ActiveFilters />
        </div>
      </div>

      {children}

      {/*
        Collapsed by default. This is reference prose -- true, worth having, and
        read once. Left expanded it occupied four lines directly under the grid
        on every visit, which on a viewport-bounded grid is space taken from the
        rows for text the reader has already absorbed. `<details>` keeps it one
        click away and costs a single line.
      */}
      <details className="group/ranks pt-1 text-xs text-muted-foreground">
        <summary className="w-fit cursor-pointer rounded font-medium marker:content-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          Reading the ranks
          <span className="ml-1 font-normal opacity-70 group-open/ranks:hidden">
            — how Investment, Score, Recommendation and Actionable Rank differ
          </span>
        </summary>
        <p className="mt-1.5 leading-relaxed">
          {investmentRankExplanation(
            factorModel,
            run.recommendation_policy_version,
          )}{" "}
          Score Rank uses uncapped evidence, Recommendation Rank groups by
          published rating, and Actionable Rank is an execution-only view that
          never changes a score or rating. Price, indicators, turnover, and
          aligned valuation ratios all use the same completed daily bar.
        </p>
      </details>
    </div>
  );
}
