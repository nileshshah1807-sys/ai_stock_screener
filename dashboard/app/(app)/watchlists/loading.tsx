import { Skeleton } from "@/components/ui/skeleton";
import { PageHeadingSkeleton, TableSkeleton } from "@/components/skeletons";

/**
 * Shown while the watchlist grid loads.
 *
 * Whole-page rather than segment-scoped like the screener's: the list selector
 * is rendered by the page itself, not a layout, because it depends on the
 * viewer's own rows. So there is no chrome that survives the navigation and
 * nothing to leave on screen.
 *
 * A row of chips then a table, matching what lands.
 */
export default function WatchlistsLoading() {
  return (
    <div
      className="space-y-4 px-4 py-5 sm:px-6"
      aria-busy="true"
      aria-live="polite"
    >
      <span className="sr-only">Loading watchlists…</span>
      <PageHeadingSkeleton />

      {/* Literal widths, not interpolated. Tailwind generates classes by
          scanning source text, so a computed `w-${n}` produces no CSS at all
          and the chips would collapse to zero width. */}
      <div className="flex flex-wrap items-center gap-1.5">
        <Skeleton className="h-8 w-24 rounded-full" />
        <Skeleton className="h-8 w-32 rounded-full" />
        <Skeleton className="h-8 w-28 rounded-full" />
        <Skeleton className="h-8 w-24 rounded-full" />
      </div>

      <TableSkeleton rows={8} />
    </div>
  );
}
