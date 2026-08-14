import { MoverListSkeleton, PageHeadingSkeleton } from "@/components/skeletons";

/**
 * Shown while the movers view loads.
 *
 * Previously this route had no loading boundary at all, so a click on "Movers"
 * left the previous page on screen for the duration of the round trip with no
 * acknowledgement -- the interaction read as ignored. Five panels, matching
 * the five buckets the page renders.
 */
export default function MoversLoading() {
  return (
    <div className="space-y-4 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading movers…</span>
      <PageHeadingSkeleton />
      <div className="grid gap-4 lg:grid-cols-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <MoverListSkeleton key={i} rows={i === 4 ? 4 : 6} />
        ))}
      </div>
    </div>
  );
}
