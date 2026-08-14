import { Skeleton } from "@/components/ui/skeleton";

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

      <div className="overflow-hidden rounded-lg border">
        <div className="flex items-center gap-4 border-b bg-muted/40 px-3 py-2.5">
          {Array.from({ length: 8 }).map((_, index) => (
            <Skeleton
              key={index}
              className="h-3"
              style={{ width: index === 1 ? "14%" : "9%" }}
            />
          ))}
        </div>

        {Array.from({ length: 12 }).map((_, row) => (
          <div
            key={row}
            className="flex items-center gap-4 border-b px-3 py-3 last:border-b-0"
          >
            {Array.from({ length: 8 }).map((_, cell) => (
              <Skeleton
                key={cell}
                className="h-3.5"
                style={{ width: cell === 1 ? "14%" : "9%" }}
              />
            ))}
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-8 w-56" />
      </div>
    </div>
  );
}
