import { Suspense } from "react";
import { Download } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { SummaryTiles } from "@/components/summary-tiles";
import { FilterBar } from "@/components/screener/filter-bar";
import { Pagination } from "@/components/screener/pagination";
import { ScreenerTable } from "@/components/screener/screener-table";
import { StockSearch } from "@/components/screener/stock-search";
import { Skeleton } from "@/components/ui/skeleton";
import { requireAccess } from "@/lib/auth";
import { parseFilters, toSearchParams } from "@/lib/filters";
import {
  getLatestRun,
  getSearchIndex,
  getSectors,
  getSnapshotPage,
  PAGE_SIZE,
} from "@/lib/queries";

// Every read is scoped to the signed-in user by RLS, so nothing on this page
// can be statically cached or shared between viewers.
export const dynamic = "force-dynamic";

function EmptyState() {
  return (
    <div className="rounded-lg border bg-card py-20 text-center">
      <p className="text-sm font-medium">No screener run has been published</p>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
        Run{" "}
        <code className="font-mono text-xs">
          python -m workers.dashboard_publisher --csv &lt;export.csv&gt;
        </code>{" "}
        to load a run, or wait for the next scheduled screener at 16:30 IST.
      </p>
    </div>
  );
}

export default async function ScreenerPage({ searchParams }: PageProps<"/">) {
  const viewer = await requireAccess();
  const params = await searchParams;

  const run = await getLatestRun();

  if (!run) {
    return (
      <AppShell run={null} viewer={viewer}>
        <div className="px-4 py-6 sm:px-6">
          <EmptyState />
        </div>
      </AppShell>
    );
  }

  const filters = parseFilters(params);
  const urlParams = toSearchParams(params);

  const [{ rows, total }, sectors, searchIndex] = await Promise.all([
    getSnapshotPage(run.run_date, filters),
    getSectors(run.run_date),
    getSearchIndex(run.run_date),
  ]);

  const exportParams = new URLSearchParams(urlParams.toString());
  exportParams.delete("page");

  return (
    <AppShell run={run} viewer={viewer}>
      <div className="space-y-4 px-4 py-5 sm:px-6">
        <SummaryTiles run={run} />

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex-1">
            <FilterBar sectors={sectors} />
          </div>
          <Suspense fallback={<Skeleton className="h-9 w-56" />}>
            <StockSearch entries={searchIndex} />
          </Suspense>
          <a
            href={`/api/export?${exportParams.toString()}`}
            className="inline-flex h-9 items-center gap-1.5 rounded-md border px-3 text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Download className="size-3.5" aria-hidden />
            <span className="hidden sm:inline">Export CSV</span>
          </a>
        </div>

        <ScreenerTable
          rows={rows}
          params={urlParams}
          sort={filters.sort ?? "investment_rank"}
          dir={
            filters.dir ??
            ((filters.sort ?? "investment_rank").endsWith("rank")
              ? "asc"
              : "desc")
          }
        />

        <Pagination
          page={filters.page ?? 1}
          pageSize={PAGE_SIZE}
          total={total}
          params={urlParams}
        />

        <p className="pt-2 text-xs leading-relaxed text-muted-foreground">
          <span className="font-medium">Reading the ranks.</span> Investment
          Rank is decision-score-first and is the primary order. Score Rank uses
          uncapped evidence, Recommendation Rank groups by published rating, and
          Actionable Rank is an execution-only view that never changes a score
          or rating. Price, indicators, turnover, and aligned valuation ratios
          all use the same completed daily bar.
        </p>
      </div>
    </AppShell>
  );
}
