import { Skeleton } from "@/components/ui/skeleton";
import { PanelSkeleton, RingSkeleton } from "@/components/skeletons";

/**
 * Shown while a stock detail page loads.
 *
 * This is the route the loading boundary matters most on: it is reached by
 * clicking a row in a 100-row grid, and it issues two Supabase reads (the full
 * snapshot row and up to 180 days of history). Without a boundary the grid sat
 * frozen under the cursor for the whole of that.
 *
 * The header block mirrors the real one exactly -- ticker, company, badge,
 * meta line -- so the page does not re-flow when the data lands.
 */
export default function StockLoading() {
  return (
    <div className="space-y-4 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading stock…</span>

      <div>
        <Skeleton className="h-3 w-28" />
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <Skeleton className="h-8 w-36" />
          <Skeleton className="h-6 w-56" />
          <Skeleton className="h-6 w-24 rounded-full" />
        </div>
        <Skeleton className="mt-2 h-3 w-80 max-w-full" />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <div className="space-y-4">
          <PanelSkeleton lines={3} />
          <PanelSkeleton lines={4} />
        </div>
        <div className="space-y-4">
          <RingSkeleton />
          <PanelSkeleton lines={2} />
        </div>
      </div>

      <PanelSkeleton lines={1} />

      <div className="grid gap-4 lg:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <PanelSkeleton key={i} lines={5} />
        ))}
      </div>
    </div>
  );
}
