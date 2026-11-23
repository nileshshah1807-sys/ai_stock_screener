import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { IndexLevel, IndexOverview } from "@/components/indices/index-overview";
import { MemberTable, readMembers } from "@/components/screener/member-table";
import { formatDate } from "@/lib/format";
import { marketFromSlug, marketPath } from "@/lib/markets";
import { getIndexChart, getIndexDirectory, getIndexMembers, getLatestRun } from "@/lib/queries";

export const dynamic = "force-dynamic";

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
  // The run does not depend on the directory, so the two reads go together.
  const [directory, run] = await Promise.all([getIndexDirectory(market.code), getLatestRun(market.code)]);
  const info = directory.find((entry) => entry.slug === indexSlug);
  if (!info) notFound();

  const [members, chart] = await Promise.all([
    info.members !== null ? getIndexMembers(market.code, info.name) : Promise.resolve([]),
    info.chart ? getIndexChart(market.code, info.name) : Promise.resolve(null),
  ]);
  const table = await readMembers(market.code, run, members, await searchParams);
  const { rated } = table;

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

      {chart ? (
        <IndexOverview
          market={market}
          name={info.name}
          row={chart}
          members={members.map((member) => ({ symbol: member.symbol, company: member.company }))}
        />
      ) : null}

      {info.members !== null ? (
        <MemberTable id="constituents-title" title="Constituents" noun="constituent" data={table} />
      ) : null}
    </div>
  );
}
