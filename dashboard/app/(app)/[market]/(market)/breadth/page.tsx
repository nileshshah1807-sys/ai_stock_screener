import type { Metadata } from "next";

import { MarketDayNotice } from "@/components/market-day-notice";
import { MarketDashboard, type BreadthList } from "@/components/market/market-dashboard";
import type { GroupKey } from "@/components/market/group-picker";
import { FiiDiiFlows } from "@/components/market/fii-dii-flows";
import { Pagination } from "@/components/screener/pagination";
import { ScreenerTable } from "@/components/screener/screener-table";
import { parseFilters, toSearchParams } from "@/lib/filters";
import { formatDate } from "@/lib/format";
import { LIST_METRICS } from "@/lib/market-breadth.mjs";
import { readLiveObject } from "@/lib/live-objects";
import { marketFromSlug, type Market } from "@/lib/markets";
import {
  getLatestRun,
  getMarketBreadth,
  getSnapshotPage,
  PAGE_SIZE,
} from "@/lib/queries";

export const metadata: Metadata = { title: "Market breadth" };
export const dynamic = "force-dynamic";

function selectedGroup(query: Record<string, string | string[] | undefined>): GroupKey {
  const first = (value: string | string[] | undefined) =>
    (Array.isArray(value) ? value[0] : value)?.trim() || "";
  const industry = first(query.industry);
  if (industry) return { scope: "industry", name: industry };
  const sector = first(query.sector);
  if (sector) return { scope: "sector", name: sector };
  return { scope: "market", name: "" };
}

/**
 * Market breadth: how many stocks are taking part in a move, not just where
 * the index is.
 *
 * An index can rise on a handful of large names while most stocks fall; the
 * share above their averages, in Stage 2, or at new highs is what says whether
 * a trend is broad. Every series is rebuilt daily by
 * tools/publish_market_breadth.py from the same closes the model scores on.
 *
 * Above the charts, NSE's FII/DII cash flows: who was buying, beside how
 * broadly. Read from the R2 object workers/market_flows.py writes; absent
 * for the US, and until the step has run.
 */
export default async function BreadthPage({ params, searchParams }: PageProps<"/[market]/breadth">) {
  const market = marketFromSlug((await params).market)!;
  const query = await searchParams;
  const selected = selectedGroup(query);
  const listed = Array.isArray(query.list) ? query.list[0] : query.list;
  const metric = listed && LIST_METRICS.includes(listed) ? listed : null;

  const [{ groups, group, indices, failed }, list, flows] = await Promise.all([
    getMarketBreadth(market.code, selected),
    metric ? breadthList(market, metric, selected, query) : Promise.resolve(null),
    // Display evidence: a failed read drops the panel, never the page.
    market.code === "NSE" ? readLiveObject(market.code, "fii-dii-flows").catch(() => null) : null,
  ]);

  return (
    <div className="space-y-6 px-4 py-5 sm:px-6">
      <MarketDayNotice />
      <div>
        <h1 className="text-title font-semibold">Market breadth</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          How many stocks take part in a move, not just where the index is.
        </p>
      </div>

      {flows?.length ? <FiiDiiFlows market={market} rows={flows} /> : null}

      <MarketDashboard
        // Remount per group so a new row starts from a clean scrub.
        key={`${selected.scope}:${selected.name}`}
        market={market}
        groups={groups}
        group={group}
        indices={indices}
        selected={selected}
        list={list}
        failed={failed}
      />

      {/* The method in one closed line: the caveats stay a click away for
          whoever wants them, out of the way of everyone else. */}
      {group ? (
        <details className="group max-w-3xl border-t pt-4 text-xs text-muted-foreground">
          <summary className="cursor-pointer list-none hover:text-foreground [&::-webkit-details-marker]:hidden">
            Breadth through {formatDate(group.last_session)} ·{" "}
            <span className="underline underline-offset-2">How it&rsquo;s counted</span>
          </summary>
          <p className="mt-2 leading-relaxed">
            Only stocks that traded that day, and only those with enough history for each measure.
            Closing prices. Today&rsquo;s universe, so delisted stocks are not in past counts.
          </p>
        </details>
      ) : null}
    </div>
  );
}

/**
 * The stocks behind one breadth chart, as the screener's own table.
 *
 * The same `getSnapshotPage` and `ScreenerTable` the Screener and Watchlists
 * use, restricted to the list through `breadth_snapshot`, so every column,
 * sort and link matches. A sector view narrows through the grid's own
 * `sector` filter -- the page's `?sector=` doubles as it -- and an industry
 * view through the snapshot's industry column.
 */
async function breadthList(
  market: Market,
  metric: string,
  selected: GroupKey,
  query: Record<string, string | string[] | undefined>,
): Promise<BreadthList> {
  const run = await getLatestRun(market.code);
  // Answer with a list either way: the sheet is already open on the press,
  // and with nothing to show it would sit on its skeleton.
  if (!run) {
    return {
      metric,
      total: 0,
      content: (
        <div className="panel py-16 text-center">
          <p className="text-sm text-muted-foreground">Couldn&rsquo;t load this list. Reload to retry.</p>
        </div>
      ),
    };
  }
  const filters = parseFilters(query);
  const urlParams = toSearchParams(query);
  const { rows, total } = await getSnapshotPage(market.code, run.run_date, filters, {
    breadth: metric,
    industry: selected.scope === "industry" ? selected.name : undefined,
  });
  const sort = filters.sort ?? "market_cap";

  return {
    metric,
    total,
    content: (
      <>
        <ScreenerTable
          rows={rows}
          params={urlParams}
          sort={sort}
          dir={filters.dir ?? (sort.endsWith("rank") ? "asc" : "desc")}
          hiddenColumns={filters.hiddenColumns}
          density={filters.density}
          emptyState={
            <div className="panel py-16 text-center">
              <p className="text-sm text-muted-foreground">No stocks on this list today.</p>
            </div>
          }
        />
        {total > PAGE_SIZE ? (
          <Pagination page={filters.page ?? 1} pageSize={PAGE_SIZE} total={total} params={urlParams} />
        ) : null}
      </>
    ),
  };
}
