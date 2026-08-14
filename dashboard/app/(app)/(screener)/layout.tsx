import { SummaryTiles } from "@/components/summary-tiles";
import { ExportLink } from "@/components/screener/export-link";
import { FilterBar } from "@/components/screener/filter-bar";
import { StockSearch } from "@/components/screener/stock-search";
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

  const [sectors, factorModel] = await Promise.all([
    trace("  getSectors", () => getSectors(run.run_date, run.row_count)),
    trace("  runUsesFactorModel", () => runUsesFactorModel(run.run_date)),
  ]);

  return (
    <div className="space-y-4 px-4 py-5 sm:px-6">
      <SummaryTiles run={run} />

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex-1">
          <FilterBar sectors={sectors} factorModel={factorModel} />
        </div>
        <StockSearch />
        <ExportLink />
      </div>

      {children}

      <p className="pt-2 text-xs leading-relaxed text-muted-foreground">
        <span className="font-medium">Reading the ranks.</span>{" "}
        {investmentRankExplanation(factorModel)} Score Rank uses uncapped
        evidence, Recommendation Rank groups by published rating, and Actionable
        Rank is an execution-only view that never changes a score or rating.
        Price, indicators, turnover, and aligned valuation ratios all use the
        same completed daily bar.
      </p>
    </div>
  );
}
