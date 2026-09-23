import Link from "next/link";
import type { Metadata } from "next";
import { ArrowLeft, Clock } from "lucide-react";

import { NewListingsBrowser } from "@/components/new-listings-browser";
import { Reveal } from "@/components/motion";
import { formatDate } from "@/lib/format";
import { marketFromSlug, marketPath } from "@/lib/markets";
import { getNewListings } from "@/lib/queries";

export const metadata: Metadata = { title: "New listings" };
export const dynamic = "force-dynamic";

/**
 * Recent listings the latest run has not rated yet.
 *
 * Its own page rather than rows mixed into the screener grid: the grid is a
 * ranked cross-section, and an unrated row inside it would have no rank, no
 * score and no rating to sort or filter on -- every one of its columns would be
 * a dash. Here each listing gets the facts it does have and, above all, the
 * reason it is waiting, which is the question this page answers.
 */
export default async function NewListingsPage({ params }: PageProps<"/[market]/new-listings">) {
  const market = marketFromSlug((await params).market)!;
  const rows = market.code === "NSE" ? await getNewListings(market.code) : [];
  const updated = rows.reduce<string | null>(
    (latest, row) => (!latest || row.updated_at > latest ? row.updated_at : latest),
    null,
  );
  const building = rows.filter((row) => row.status === "insufficient_history").length;

  return (
    <div className="space-y-4 px-4 py-5 sm:px-6">
      <div>
        <Link
          href={marketPath(market.slug)}
          className="inline-flex items-center gap-1 rounded-full text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ArrowLeft className="size-3" aria-hidden />
          Back to screener
        </Link>
        <h1 className="mt-2 text-title font-semibold">New listings</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Companies listed on the {market.label} mainboard in the last twelve months that the
          screener has not rated yet. A stock needs 60 sessions of price history and enough
          daily turnover before the model can score it; each one moves into the screener
          automatically once it qualifies.
        </p>
      </div>

      {market.code !== "NSE" ? (
        <div className="panel px-5 py-10 text-center">
          <p className="text-sm font-medium">New-listing tracking is available for NSE only.</p>
          <p className="mt-1 text-xs text-muted-foreground">
            The {market.label} universe source does not publish listing dates.
          </p>
        </div>
      ) : rows.length ? (
        <Reveal className="panel overflow-hidden">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b px-4 py-3 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5 font-medium text-foreground">
              <Clock className="size-3.5" aria-hidden />
              {rows.length} not yet rated
            </span>
            <span>{building} building price history</span>
            {updated ? <span className="sm:ml-auto">Updated {formatDate(updated)}</span> : null}
          </div>
          <NewListingsBrowser rows={rows} market={market} />
        </Reveal>
      ) : (
        <div className="panel px-5 py-10 text-center">
          <p className="text-sm font-medium">No recent listings are waiting for a rating.</p>
          <p className="mt-1 text-xs text-muted-foreground">
            The list is refreshed three times a day.
          </p>
        </div>
      )}
    </div>
  );
}
