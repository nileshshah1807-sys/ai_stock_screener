import { LiveMoversSkeleton } from "@/components/market/live-movers";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Mirrors the Market page: heading, today's movers (both markets list them),
 * the control row, then a grid of chart cards -- so
 * nothing moves when the page streams in over it.
 */
export default function MarketLoading() {
  return (
    <div className="space-y-6 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading the market…</span>
      <Skeleton className="h-9 w-40" />
      <LiveMoversSkeleton />
      <div className="flex flex-wrap gap-3 py-2">
        <Skeleton className="h-9 w-36 rounded-md" />
        <Skeleton className="h-8 w-28 rounded-lg" />
        <Skeleton className="h-8 w-full rounded-lg sm:ml-auto sm:w-80" />
      </div>
      <div className="space-y-3">
        <Skeleton className="h-5 w-44" />
        <div className="grid gap-4 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="panel space-y-3 p-4 sm:p-5">
              <Skeleton className="h-3 w-32" />
              <Skeleton className="h-7 w-24" />
              <Skeleton className="h-3 w-40" />
              <Skeleton className="h-32 w-full rounded-row sm:h-[168px]" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
