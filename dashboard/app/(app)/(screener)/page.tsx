import { Pagination } from "@/components/screener/pagination";
import { ScreenerTable } from "@/components/screener/screener-table";
import { parseFilters, toSearchParams } from "@/lib/filters";
import { getLatestRun, getSnapshotPage, PAGE_SIZE } from "@/lib/queries";
import { mark, trace } from "@/lib/trace";

// Reads go through the viewer's session, and the grid reflects whatever filters
// are in the URL, so this segment is rendered per request. Note this is about
// the request being authenticated and parameterised, not about the rows being
// per-user: screener_snapshot carries no viewer column, and RLS gates access to
// the table wholesale rather than filtering it row by row.
export const dynamic = "force-dynamic";

function EmptyState() {
  return (
    <div className="panel animate-rise py-20 text-center">
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

/**
 * The grid itself.
 *
 * Deliberately thin: the run manifest, sector list, factor-model probe and all
 * the filter chrome live in the surrounding layouts, which do not re-render on
 * navigation. The single query below is the only work a sort, filter or page
 * change should cost.
 */
export default async function ScreenerPage({ searchParams }: PageProps<"/">) {
  mark("(screener)/page RENDERED");
  const run = await getLatestRun();

  if (!run) {
    return (
      <div className="px-4 py-6 sm:px-6">
        <EmptyState />
      </div>
    );
  }

  const params = await searchParams;
  const filters = parseFilters(params);
  const urlParams = toSearchParams(params);

  const { rows, total } = await trace("  getSnapshotPage", () =>
    getSnapshotPage(run.run_date, filters),
  );

  return (
    <div className="space-y-4">
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
    </div>
  );
}
