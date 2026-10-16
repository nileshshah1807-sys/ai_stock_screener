import { Suspense } from "react";
import type { Metadata } from "next";

import { MarketDashboard, type BreadthList } from "@/components/market/market-dashboard";
import type { GroupKey } from "@/components/market/group-picker";
import { LiveMovers, LiveMoversSkeleton } from "@/components/market/live-movers";
import { Pagination } from "@/components/screener/pagination";
import { ScreenerTable } from "@/components/screener/screener-table";
import { parseFilters, toSearchParams } from "@/lib/filters";
import { formatDate } from "@/lib/format";
import { LIST_METRICS } from "@/lib/market-breadth.mjs";
import { marketFromSlug, type Market } from "@/lib/markets";
import {
  getLatestRun,
  getLiveMarket,
  getMarketBreadth,
  getSnapshotPage,
  PAGE_SIZE,
} from "@/lib/queries";

export const metadata: Metadata = { title: "Market" };
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
 * Above the breadth, today's movers within each index, from the five-minute
 * quotes (components/market/live-movers.tsx).
 */
export default async function MarketPage({ params, searchParams }: PageProps<"/[market]/market">) {
  const market = marketFromSlug((await params).market)!;
  const query = await searchParams;
  const selected = selectedGroup(query);
  const listed = Array.isArray(query.list) ? query.list[0] : query.list;
  const metric = listed && LIST_METRICS.includes(listed) ? listed : null;

  const [{ groups, group, indices }, list] = await Promise.all([
    getMarketBreadth(market.code, selected),
    metric ? breadthList(market, metric, selected, query) : Promise.resolve(null),
  ]);
  const universe = groups.find((entry) => entry.scope === "market")?.members ?? null;

  return (
    <div className="space-y-6 px-4 py-5 sm:px-6">
      <div>
        <h1 className="text-title font-semibold">Market</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          How broadly {market.label} stocks are participating
          {universe ? ` — ${universe.toLocaleString(market.locale)} stocks the screener rates` : ""},
          session by session. Hover or drag across any chart to read every chart on that day.
        </p>
      </div>

      {/* Today's prices first: what is moving now is the question a reader
          arrives with; breadth below is the slower, session-by-session view.
          Streamed, so the page never waits on the read: the skeleton holds
          its place until it lands. */}
      {market.liveIndices ? (
        <Suspense fallback={<LiveMoversSkeleton />}>
          <LiveMoversSection market={market} />
        </Suspense>
      ) : null}

      <MarketDashboard
        // Remount per group so a new row starts from a clean scrub.
        key={`${selected.scope}:${selected.name}`}
        market={market}
        groups={groups}
        group={group}
        indices={indices}
        selected={selected}
        list={list}
      />

      {group ? (
        <p className="max-w-3xl border-t pt-4 text-xs leading-relaxed text-muted-foreground">
          Updated through {formatDate(group.last_session)}. Each day counts only the stocks that
          traded that day, and each measure only the stocks with enough history for it — a stock
          listed four months ago counts toward the 50-day EMA but not the 200-day. Highs and lows
          use closing prices. Stage and RS rating use the screener&rsquo;s own rules, replayed
          over each stock&rsquo;s history. History covers today&rsquo;s universe, so stocks that
          have since delisted are not in earlier counts.
        </p>
      ) : null}
    </div>
  );
}

/** Today's movers, read on the server and kept current in the browser. */
async function LiveMoversSection({ market }: { market: Market }) {
  return <LiveMovers market={market} initial={await getLiveMarket(market.code)} />;
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
): Promise<BreadthList | null> {
  const run = await getLatestRun(market.code);
  if (!run) return null;
  const filters = parseFilters(query);
  const urlParams = toSearchParams(query);
  const { rows, total } = await getSnapshotPage(market.code, run.run_date, filters, {
    breadth: metric,
    industry: selected.scope === "industry" ? selected.name : undefined,
  });
  const sort = filters.sort ?? "investment_rank";

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
              <p className="text-sm font-medium">No stocks on this list today</p>
              <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
                None of the stocks behind this count were in the latest screener run.
              </p>
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
