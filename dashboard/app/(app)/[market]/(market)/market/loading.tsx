import { LiveMoversSkeleton } from "@/components/market/live-movers";

/** Mirrors Today's movers, so nothing moves when the page streams in over it. */
export default function MoversLoading() {
  return (
    <div className="space-y-6 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading today&rsquo;s movers…</span>
      <LiveMoversSkeleton />
    </div>
  );
}
