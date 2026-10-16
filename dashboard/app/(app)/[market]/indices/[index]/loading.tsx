import { PageHeadingSkeleton, TableSkeleton } from "@/components/skeletons";
import { Skeleton } from "@/components/ui/skeleton";

/** Mirrors an index page: heading, the chart, then the constituents table. */
export default function IndexLoading() {
  return (
    <div className="space-y-6 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading index…</span>
      <PageHeadingSkeleton />
      <div className="space-y-3">
        <Skeleton className="h-9 w-72 rounded-full" />
        <div className="panel space-y-3 p-4 sm:p-5">
          <Skeleton className="h-3 w-32" />
          <Skeleton className="h-7 w-24" />
          <Skeleton className="h-[168px] w-full rounded-row" />
        </div>
      </div>
      <div className="space-y-3">
        <Skeleton className="h-5 w-36" />
        <TableSkeleton rows={10} />
      </div>
    </div>
  );
}
