import { PageHeadingSkeleton } from "@/components/skeletons";
import { Skeleton } from "@/components/ui/skeleton";

/** Mirrors the Market page: heading, control row, then a grid of chart cards. */
export default function MarketLoading() {
  return (
    <div className="space-y-6 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading market breadth…</span>
      <PageHeadingSkeleton />
      <div className="flex flex-wrap gap-3">
        <Skeleton className="h-9 w-36 rounded-full" />
        <Skeleton className="h-9 w-28 rounded-full" />
        <Skeleton className="h-9 w-72 rounded-full sm:ml-auto" />
      </div>
      <div className="space-y-3">
        <Skeleton className="h-5 w-44" />
        <div className="grid gap-4 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="panel space-y-3 p-4 sm:p-5">
              <Skeleton className="h-3 w-32" />
              <Skeleton className="h-7 w-24" />
              <Skeleton className="h-3 w-40" />
              <Skeleton className="h-[168px] w-full rounded-row" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
