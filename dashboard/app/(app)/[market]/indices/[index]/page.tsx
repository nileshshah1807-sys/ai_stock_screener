import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { LiveSearch } from "@/components/filters/live-search";
import { IndexLevel, IndexOverview } from "@/components/indices/index-overview";
import { Pagination } from "@/components/screener/pagination";
import { ScreenerTable } from "@/components/screener/screener-table";
import { ViewOptions } from "@/components/screener/view-options";
import { parseFilters, toSearchParams } from "@/lib/filters";
import { formatDate } from "@/lib/format";
import { marketFromSlug, marketPath } from "@/lib/markets";
import {
  getIndexChart,
  getIndexDirectory,
  getIndexMembers,
  getLatestRun,
  getRatedSymbols,
  getSnapshotPage,
  PAGE_SIZE,
} from "@/lib/queries";

export const dynamic = "force-dynamic";

/** Page and search are about the list before a new search or sort. */
const SEARCH_RESETS = ["page"];

export async function generateMetadata({ params }: PageProps<"/[market]/indices/[index]">) {
  const { market: slug, index } = await params;
  const market = marketFromSlug(slug);
  const info = market
    ? (await getIndexDirectory(market.code)).find((entry) => entry.slug === index)
    : undefined;
  return { title: info ? `${info.name} · ${market!.label}` : "Index" };
}

/**
 * One index: where it is trading, and the stocks it is made of, in the
 * screener's own table.
 *
 * The constituents are `index_members` (re-read daily by
 * workers/live_quotes.py) and the table is `getSnapshotPage` restricted to
 * them, so every column, sort, view option and link is the screener's, and
 * Price and 1D are live during the session as they are there. An index of
 * 500 is ~4 KB of symbols in the read's `in` filter, well inside a URL.
 *
 * A constituent the screener does not rate has no row to show; those are
 * named under the table rather than silently dropped, so the count above it
 * still adds up. An index with no published constituents -- the Nasdaq
 * Composite, the Russell 2000 -- shows its chart and says so.
 */
export default async function IndexPage({ params, searchParams }: PageProps<"/[market]/indices/[index]">) {
  const { market: slug, index: indexSlug } = await params;
  const market = marketFromSlug(slug)!;
  const directory = await getIndexDirectory(market.code);
  const info = directory.find((entry) => entry.slug === indexSlug);
  if (!info) notFound();

  const query = await searchParams;
  const filters = parseFilters(query);
  const urlParams = toSearchParams(query);

  const [run, members, chart] = await Promise.all([
    getLatestRun(market.code),
    info.members !== null ? getIndexMembers(market.code, info.name) : Promise.resolve([]),
    info.chart ? getIndexChart(market.code, info.name) : Promise.resolve(null),
  ]);
  const symbols = members.map((member) => member.symbol);

  const [page, rated] =
    run && symbols.length
      ? await Promise.all([
          getSnapshotPage(market.code, run.run_date, filters, { symbols }),
          getRatedSymbols(market.code, run.run_date, symbols),
        ])
      : [{ rows: [], total: 0 }, new Set<string>()];
  const unrated = members.filter((member) => !rated.has(member.symbol));
  const sort = filters.sort ?? "investment_rank";

  return (
    <div className="space-y-6 px-4 py-5 sm:px-6">
      <div>
        <Link
          href={marketPath(market.slug, "/indices")}
          className="inline-flex items-center gap-1 rounded-md text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ArrowLeft className="size-3" aria-hidden />
          All indices
        </Link>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="text-title font-semibold">{info.name}</h1>
          <span className="rounded-md bg-(--control) px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">
            {market.label}
          </span>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          {info.members !== null
            ? `${info.members.toLocaleString(market.locale)} constituents${
                run ? ` · ${rated.size.toLocaleString(market.locale)} rated in the ${formatDate(run.run_date)} run` : ""
              }`
            : "Index level. Constituents are not published for this index."}
        </p>
        {!chart ? (
          <div className="mt-3">
            <IndexLevel market={market} name={info.name} />
          </div>
        ) : null}
      </div>

      {chart ? <IndexOverview market={market} name={info.name} row={chart} /> : null}

      {info.members !== null ? (
        <section aria-labelledby="constituents-title" className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
            <div>
              <h2 id="constituents-title" className="text-lead font-semibold tracking-[-0.011em]">
                Constituents
              </h2>
              <p className="mt-0.5 text-sm text-muted-foreground">
                Ranked and scored by the screener, in its own columns. Sort by any column.
              </p>
            </div>
            <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
              <LiveSearch
                label={`Search ${info.name}`}
                placeholder="Search constituents…"
                resets={SEARCH_RESETS}
                className="min-w-0 flex-1 sm:w-64 sm:flex-none"
              />
              <ViewOptions factorModel={run?.factor_model_applied ?? false} />
            </div>
          </div>

          <ScreenerTable
            rows={page.rows}
            params={urlParams}
            sort={sort}
            dir={filters.dir ?? (sort.endsWith("rank") ? "asc" : "desc")}
            hiddenColumns={filters.hiddenColumns}
            density={filters.density}
            emptyState={
              <div className="panel py-16 text-center">
                <p className="text-sm font-medium">
                  {filters.q ? `No constituent matches “${filters.q}”` : "No constituent is in the latest run"}
                </p>
                <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
                  {filters.q
                    ? "Search by ticker or company name."
                    : "The screener has not rated any of this index's stocks yet."}
                </p>
              </div>
            }
          />
          {page.total > PAGE_SIZE ? (
            <Pagination page={filters.page ?? 1} pageSize={PAGE_SIZE} total={page.total} params={urlParams} />
          ) : null}

          {unrated.length ? (
            <details className="group/unrated text-sm">
              <summary className="w-fit cursor-pointer rounded text-xs font-medium text-muted-foreground marker:content-none hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                {unrated.length} {unrated.length === 1 ? "constituent" : "constituents"} the screener does not rate
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
                    {member.company ? (
                      <span className="ml-1.5 text-muted-foreground">{member.company}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
