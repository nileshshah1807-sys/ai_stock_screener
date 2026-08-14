import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Shared loading placeholders.
 *
 * Every one of these mirrors the real component's box model -- same panel
 * radius, same padding, same row height, same column count. That is the whole
 * point: a placeholder whose geometry differs from the content replacing it
 * causes a layout jump on arrival, which is worse than showing nothing. Row
 * and column counts below match the first screenful of the real thing.
 */

/** Mirrors SummaryTiles: one panel, six cells, hairline gap dividers. */
export function KpiBandSkeleton() {
  return (
    <div className="panel grid grid-cols-2 gap-px overflow-hidden bg-border sm:grid-cols-3 xl:grid-cols-6">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 bg-card p-4">
          <Skeleton className="h-11 w-2 rounded-full" />
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-8 w-16" />
            <Skeleton className="h-2.5 w-14" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Mirrors ScreenerTable's header plus its first screenful of rows. */
export function TableSkeleton({ rows = 12 }: { rows?: number }) {
  return (
    <div className="panel overflow-hidden">
      <div className="flex items-center gap-4 border-b bg-muted/40 px-3 py-3">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton
            key={i}
            className="h-3"
            style={{ width: i === 1 ? "14%" : "9%" }}
          />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, row) => (
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
  );
}

/** Mirrors Panel: same radius, same padding, title then body. */
export function PanelSkeleton({
  lines = 4,
  className,
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={cn("panel p-5 sm:p-6", className)}>
      <Skeleton className="h-5 w-40" />
      <Skeleton className="mt-2 h-3 w-64" />
      <div className="mt-5 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
        {Array.from({ length: lines * 2 }).map((_, i) => (
          <div key={i} className="space-y-1.5">
            <Skeleton className="h-2.5 w-20" />
            <Skeleton className="h-4 w-24" />
          </div>
        ))}
      </div>
    </div>
  );
}

/** Mirrors the DecisionScore ring inside its panel. */
export function RingSkeleton() {
  return (
    <div className="panel p-5 sm:p-6">
      <Skeleton className="h-5 w-36" />
      <Skeleton className="mt-2 h-3 w-56" />
      <div className="mt-6 flex justify-center">
        <Skeleton className="size-44 rounded-full" />
      </div>
    </div>
  );
}

/** Mirrors a MoverList panel: header block then a run of rows. */
export function MoverListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="panel overflow-hidden">
      <div className="border-b px-4 py-3">
        <Skeleton className="h-4 w-36" />
        <Skeleton className="mt-2 h-2.5 w-56" />
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 border-b px-4 py-2.5 last:border-b-0">
          <Skeleton className="h-3 w-6" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-2.5 w-40" />
          </div>
          <Skeleton className="h-5 w-16 rounded-full" />
        </div>
      ))}
    </div>
  );
}

/** Page title block, used at the top of every route-level fallback. */
export function PageHeadingSkeleton() {
  return (
    <div className="space-y-2">
      <Skeleton className="h-9 w-56" />
      <Skeleton className="h-3.5 w-96 max-w-full" />
    </div>
  );
}
