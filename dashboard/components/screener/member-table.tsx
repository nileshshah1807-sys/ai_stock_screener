import { LiveSearch } from "@/components/filters/live-search";
import { Pagination } from "@/components/screener/pagination";
import { ScreenerTable } from "@/components/screener/screener-table";
import { ViewOptions } from "@/components/screener/view-options";
import { parseFilters, toSearchParams } from "@/lib/filters";
import type { MarketCode } from "@/lib/markets";
import { getRatedSymbols, getSnapshotPage, PAGE_SIZE } from "@/lib/queries";
import type { ScreenerRun } from "@/lib/types";

/** Page and search are about the list before a new search or sort. */
const SEARCH_RESETS = ["page"];

type Member = { symbol: string; company: string | null };
type Query = Record<string, string | string[] | undefined>;

/**
 * A set of stocks (an index's constituents, a sector's members) read as the
 * screener's own rows: `getSnapshotPage` restricted to them, so every column,
 * sort, view option and live figure is the screener's. A member the run does
 * not rate has no row; `rated` lets the caller name those apart. The largest
 * set, an NSE sector of ~840, is a ~8 KB `in` filter; PostgREST takes 15 KB.
 */
export async function readMembers(market: MarketCode, run: ScreenerRun | null, members: Member[], query: Query) {
  const filters = parseFilters(query);
  const symbols = members.map((member) => member.symbol);
  const [page, rated] =
    run && symbols.length
      ? await Promise.all([
          getSnapshotPage(market, run.run_date, filters, { symbols }),
          getRatedSymbols(market, run.run_date, symbols),
        ])
      : [{ rows: [], total: 0 }, new Set<string>()];
  return { filters, params: toSearchParams(query), page, rated, members, factorModel: run?.factor_model_applied ?? false };
}

/**
 * The screener's grid for a set of stocks, with its search, column picker and
 * pagination, and the members it does not rate listed under it.
 */
export function MemberTable({
  id,
  title,
  noun,
  data,
}: {
  id: string;
  title: string;
  /** "constituent", "stock": the empty state, search label and unrated list. */
  noun: string;
  data: Awaited<ReturnType<typeof readMembers>>;
}) {
  const { filters, params, page, rated, members, factorModel } = data;
  const sort = filters.sort ?? "market_cap";
  const unrated = members.filter((member) => !rated.has(member.symbol));
  return (
    <section aria-labelledby={id} className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <h2 id={id} className="text-lead font-semibold tracking-[-0.011em]">
          {title}
        </h2>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          <LiveSearch
            label={`Search ${title}`}
            placeholder="Search ticker or name…"
            resets={SEARCH_RESETS}
            className="min-w-0 flex-1 sm:w-64 sm:flex-none"
          />
          <ViewOptions factorModel={factorModel} />
        </div>
      </div>

      <ScreenerTable
        rows={page.rows}
        params={params}
        sort={sort}
        dir={filters.dir ?? (sort.endsWith("rank") ? "asc" : "desc")}
        hiddenColumns={filters.hiddenColumns}
        density={filters.density}
        emptyState={
          <div className="panel py-16 text-center">
            <p className="text-sm font-medium">
              {filters.q ? `No ${noun} matches “${filters.q}”` : `No ${noun} is in the latest run`}
            </p>
            <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
              {filters.q ? "Search by ticker or company name." : "The screener has not rated any of these stocks yet."}
            </p>
          </div>
        }
      />
      {page.total > PAGE_SIZE ? (
        <Pagination page={filters.page ?? 1} pageSize={PAGE_SIZE} total={page.total} params={params} />
      ) : null}

      {unrated.length ? (
        <details className="group/unrated text-sm">
          <summary className="w-fit cursor-pointer rounded text-xs font-medium text-muted-foreground marker:content-none hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
            {unrated.length} {unrated.length === 1 ? noun : `${noun}s`} the screener does not rate
            <span className="ml-1 font-normal opacity-70 group-open/unrated:hidden">
              — too new or too thinly traded to score; no stock page
            </span>
          </summary>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {unrated.map((member) => (
              <li
                key={member.symbol}
                title={member.company ?? undefined}
                className="rounded-md bg-(--control) px-2.5 py-1 text-xs"
              >
                <span className="font-mono font-semibold">{member.symbol}</span>
                {member.company ? <span className="ml-1.5 text-muted-foreground">{member.company}</span> : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
