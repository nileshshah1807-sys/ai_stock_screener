import type { Metadata } from "next";
import { BookmarkPlus, ListPlus } from "lucide-react";

import { Pagination } from "@/components/screener/pagination";
import { ScreenerTable } from "@/components/screener/screener-table";
import { StageBreakAlert } from "@/components/watchlist/stage-break-alert";
import { WatchlistRowAction } from "@/components/watchlist/watchlist-row-action";
import { WatchlistSearch } from "@/components/watchlist/watchlist-search";
import { WatchlistSelector } from "@/components/watchlist/watchlist-selector";
import { parseFilters, toSearchParams } from "@/lib/filters";
import { formatDate } from "@/lib/format";
import { marketFromSlug } from "@/lib/markets";
import {
  getLatestRun,
  getSnapshotPage,
  getStageBreaks,
  PAGE_SIZE,
} from "@/lib/queries";
import { getWatchlists, resolveWatchlist } from "@/lib/watchlists";

export const metadata: Metadata = { title: "Watchlists" };
// Per-viewer data behind an ownership policy, so nothing here is cacheable
// across requests, and the shown rows follow the URL's filters.
export const dynamic = "force-dynamic";

function Panel({
  title,
  body,
  icon: Icon,
}: {
  title: string;
  body: string;
  icon: typeof ListPlus;
}) {
  return (
    <div className="panel animate-rise py-16 text-center">
      <Icon className="mx-auto size-5 text-muted-foreground" aria-hidden />
      <p className="mt-3 text-sm font-medium">{title}</p>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
        {body}
      </p>
    </div>
  );
}

/**
 * Watchlists: the screener grid, restricted to symbols the viewer chose.
 *
 * Deliberately thin, and deliberately not its own table. It calls the same
 * `getSnapshotPage` the screener does, with a `symbols` restriction, and renders
 * the same `ScreenerTable` with a trailing remove control. Every column, tooltip,
 * frozen column, sort key and density setting is therefore shared: adding a
 * column to the registry adds it here too, and there is no second grid to keep
 * in step.
 *
 * One consequence worth stating: the rows are the *current run's* evidence for
 * those symbols. A watchlist is a set of tickers, not a snapshot of scores, so
 * it re-reads every day and shows what the model thinks now.
 */
export default async function WatchlistsPage({
  params,
  searchParams,
}: PageProps<"/[market]/watchlists">) {
  const market = marketFromSlug((await params).market)!;
  // Named `query` rather than `params`, which is now the route params prop.
  const query = await searchParams;
  const filters = parseFilters(query);
  const urlParams = toSearchParams(query);

  // Independent reads. The run manifest does not depend on which lists exist.
  const [run, lists] = await Promise.all([
    getLatestRun(market.code),
    getWatchlists(market.code),
  ]);

  const requested = Array.isArray(query.list) ? query.list[0] : query.list;
  const selected = resolveWatchlist(lists, requested);

  // Independent reads again: the alert covers the whole list regardless of the
  // grid's filters and page, so it is not derived from the grid's rows.
  const [{ rows, total }, breaks] = selected?.symbols.length
    ? await Promise.all([
        getSnapshotPage(market.code, run?.run_date ?? "", filters, {
          symbols: selected.symbols,
        }),
        getStageBreaks(market.code, run?.run_date ?? "", selected.addedAt),
      ])
    : [{ rows: [], total: 0 }, []];

  // Symbols on the list that the current run did not score: delisted, or simply
  // not selected this time. Named explicitly rather than silently dropped, so a
  // list of 12 that shows 11 rows explains the twelfth.
  const scored = new Set(rows.map((row) => row.symbol));
  const unscored =
    selected && total <= PAGE_SIZE
      ? selected.symbols.filter((symbol) => !scored.has(symbol))
      : [];

  return (
    <div className="space-y-4 px-4 py-5 sm:px-6">
      <div>
        <h1 className="text-title font-semibold">Watchlists</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {run ? (
            <>
              Your own lists, scored against the {formatDate(run.run_date)} run.
              A list holds tickers, not scores, so it re-reads every day.
            </>
          ) : (
            <>No screener run has been published yet.</>
          )}
        </p>
      </div>

      {/* Selector and the add control on one row: choosing a list and filling
          it are the same task, and the add control is meaningless without a
          list selected, so it appears only once there is one. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex-1">
          <WatchlistSelector lists={lists} selectedId={selected?.id ?? null} />
        </div>
        {selected ? (
          /*
           * Keyed on the list and its membership, so React remounts it whenever
           * either changes. The picker seeds its tick state from `present` once,
           * at mount -- without this, removing a symbol from the grid would
           * leave the dialog still showing it as on the list.
           *
           * Safe to remount: the picker defers its refresh until it closes, so
           * this key never changes while the dialog is open.
           */
          <WatchlistSearch
            key={`${selected.id}:${selected.symbols.join(",")}`}
            watchlistId={selected.id}
            watchlistName={selected.name}
            present={selected.symbols}
          />
        ) : null}
      </div>

      {!lists.length ? (
        <Panel
          icon={ListPlus}
          title="No watchlists yet"
          body="Create one above, then add stocks with the search box, from a stock's own page, or by pressing ⌘K. Lists are private to your account."
        />
      ) : !selected?.symbols.length ? (
        <Panel
          icon={BookmarkPlus}
          title={`“${selected?.name}” is empty`}
          body="Use “Add stocks…” above, or press ⌘K, and search by ticker or company name. Everything the screener shows -- score, factors, evidence, liquidity -- shows here too."
        />
      ) : (
        <>
          <StageBreakAlert breaks={breaks} market={market} />

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
            hiddenColumns={filters.hiddenColumns}
            density={filters.density}
            rowAction={{
              label: "Remove",
              render: (row) => (
                <WatchlistRowAction
                  watchlistId={selected.id}
                  symbol={row.symbol}
                />
              ),
            }}
            emptyState={
              <Panel
                icon={BookmarkPlus}
                title="No rows for this list"
                body="None of the symbols on this list were scored by the current run, or the active filters exclude all of them."
              />
            }
          />

          <Pagination
            page={filters.page ?? 1}
            pageSize={PAGE_SIZE}
            total={total}
            params={urlParams}
          />

          {unscored.length ? (
            <p className="text-xs leading-relaxed text-muted-foreground">
              <span className="font-medium">Not in this run.</span>{" "}
              {unscored.join(", ")}. A watched symbol stays on the list when a
              run stops covering it -- delisted, or not selected into the
              universe -- rather than disappearing without explanation.
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
