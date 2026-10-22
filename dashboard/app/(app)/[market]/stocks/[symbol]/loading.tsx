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
 * Each block mirrors the page it stands in for -- the hero panel with its
 * identity row, six tiles and 300px chart, the tab strip, then the Overview's
 * score column beside factor blocks and waterfall -- so nothing re-flows when
 * the data lands. Keep it in step with page.tsx.
 */
export default function StockLoading() {
  return (
    <div className="space-y-4 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading stock…</span>

      <div className="panel p-5 sm:p-6">
        <Skeleton className="h-3 w-28" />
        <div className="mt-3 flex items-center gap-3">
          <Skeleton className="size-14 shrink-0 rounded-xl" />
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            <Skeleton className="h-8 w-28" />
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-6 w-20 rounded-full" />
          </div>
          <Skeleton className="ml-auto h-8 w-20 shrink-0 self-start rounded-full" />
        </div>
        <Skeleton className="mt-2 h-3 w-80 max-w-full" />

        <div className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-row bg-border sm:grid-cols-3 lg:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="space-y-1.5 bg-card px-4 py-3">
              <Skeleton className="h-2.5 w-10" />
              <Skeleton className="h-5 w-16" />
            </div>
          ))}
        </div>

        <div className="mt-4 space-y-3">
          <Skeleton className="h-8 w-64 max-w-full rounded-full" />
          <Skeleton className="h-[300px] w-full rounded-row" />
          <Skeleton className="h-3 w-3/4" />
        </div>
      </div>

      <div className="flex justify-center sm:justify-start">
        <Skeleton className="h-10 w-80 max-w-full rounded-full" />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
        <RingSkeleton />
        <div className="space-y-4">
          <PanelSkeleton lines={3} />
          <PanelSkeleton lines={2} />
        </div>
      </div>
    </div>
  );
}
