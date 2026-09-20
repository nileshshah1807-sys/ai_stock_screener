import { Skeleton } from "@/components/ui/skeleton";
import { TableSkeleton } from "@/components/skeletons";

/**
 * Shown while the grid query runs.
 *
 * Scoped to this segment rather than the whole shell: the summary tiles, filter
 * bar and search live in the layout and stay on screen and interactive, so a
 * sort or filter swaps only the rows. Row count matches PAGE_SIZE's first
 * screenful so the surrounding layout does not shift when the data lands.
 */
export default function ScreenerLoading() {
  return (
    <div className="space-y-4" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading results…</span>

      <TableSkeleton rows={12} />

      <div className="flex items-center justify-between">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-9 w-56 rounded-full" />
      </div>
    </div>
  );
}
