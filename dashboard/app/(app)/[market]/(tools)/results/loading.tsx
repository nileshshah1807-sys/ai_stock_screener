import { PageHeadingSkeleton } from "@/components/skeletons";
import { Skeleton } from "@/components/ui/skeleton";

/** Mirrors the Results page: heading, filter row, then a day of result cards. */
export default function ResultsLoading() {
  return (
    <div className="space-y-4 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading quarterly results…</span>
      <PageHeadingSkeleton />
      <div className="flex flex-wrap gap-1.5">
        <Skeleton className="h-8 w-24 rounded-full" />
        <Skeleton className="h-8 w-36 rounded-full" />
      </div>
      <Skeleton className="h-5 w-28" />
      <div className="grid gap-4 xl:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="panel space-y-3 p-4">
            <div className="flex justify-between">
              <div className="space-y-1.5">
                <Skeleton className="h-4 w-44" />
                <Skeleton className="h-3 w-16" />
              </div>
              <Skeleton className="h-3 w-28" />
            </div>
            <Skeleton className="h-8 w-52 rounded-full" />
            {Array.from({ length: 5 }).map((__, row) => (
              <Skeleton key={row} className="h-6 w-full" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
