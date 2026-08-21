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
        {investmentRankExplanation(
          factorModel,
          run.recommendation_policy_version,
        )}{" "}
        Score Rank uses uncapped
        evidence, Recommendation Rank groups by published rating, and Actionable
        Rank is an execution-only view that never changes a score or rating.
        Price, indicators, turnover, and aligned valuation ratios all use the
        same completed daily bar.
      </p>
    </div>
  );
}
