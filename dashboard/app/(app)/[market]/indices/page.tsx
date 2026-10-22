import Link from "next/link";
import type { Metadata } from "next";
import { ChartLine, ChevronRight } from "lucide-react";

import { IndexLevel } from "@/components/indices/index-overview";
import { marketFromSlug, marketPath } from "@/lib/markets";
import { getIndexDirectory } from "@/lib/queries";

export const metadata: Metadata = { title: "Indices" };
export const dynamic = "force-dynamic";

/**
 * Every index the market publishes a chart or a constituent list for, each
 * opening its own page. The header search finds the same list; this is
 * where "All indices" on an index page goes back to.
 */
export default async function IndicesPage({ params }: PageProps<"/[market]/indices">) {
  const market = marketFromSlug((await params).market)!;
  const indices = await getIndexDirectory(market.code);
  const names = indices.map((index) => index.name);

  return (
    <div className="space-y-6 px-4 py-5 sm:px-6">
      <div>
        <h1 className="text-title font-semibold">Indices</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          The {market.label} indices the dashboard follows. Open one for its chart and the stocks
          it is made of, ranked by the screener.
        </p>
      </div>

      {indices.length ? (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {indices.map((index) => (
            <li key={index.slug}>
              <Link
                href={marketPath(market.slug, `/indices/${index.slug}`)}
                className="panel press group/index flex h-full flex-col gap-3 p-4 hover:bg-(--control) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="flex items-center gap-3">
                  <span
                    aria-hidden
                    className="flex size-9 shrink-0 items-center justify-center rounded-md bg-(--control) text-foreground"
                  >
                    <ChartLine className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{index.name}</span>
                    <span className="block text-xs text-muted-foreground">
                      {index.members !== null
                        ? `${index.members.toLocaleString(market.locale)} constituents`
                        : "Chart only"}
                    </span>
                  </span>
                  <ChevronRight
                    aria-hidden
                    className="size-4 shrink-0 text-muted-foreground transition-transform duration-(--duration-fast) group-hover/index:translate-x-0.5"
                  />
                </span>
                <IndexLevel market={market} name={index.name} batch={names} compact />
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <div className="panel px-5 py-12 text-center">
          <p className="text-sm font-medium">No index is published for {market.label} yet.</p>
        </div>
      )}
    </div>
  );
}
