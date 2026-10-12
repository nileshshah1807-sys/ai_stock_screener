import { PageHeadingSkeleton } from "@/components/skeletons";
import { Skeleton } from "@/components/ui/skeleton";

/** Mirrors the Concalls page: heading, filter row, then a day of call rows. */
export default function ConcallsLoading() {
  return (
    <div className="space-y-4 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading earnings calls…</span>
      <PageHeadingSkeleton />
      <div className="flex flex-wrap gap-1.5">
        <Skeleton className="h-8 w-24 rounded-full" />
        <Skeleton className="h-8 w-36 rounded-full" />
      </div>
      <div className="panel overflow-hidden">
        <div className="border-b px-4 py-3">
          <Skeleton className="h-5 w-28" />
        </div>
        <div className="divide-y">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="grid gap-x-6 gap-y-3 px-4 py-3.5 md:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_minmax(0,13rem)]"
            >
              <div className="space-y-2">
                <Skeleton className="h-3 w-20" />
                <Skeleton className="h-3 w-36" />
                <Skeleton className="h-5 w-28 rounded-full" />
              </div>
              <div className="space-y-2">
                <Skeleton className="h-3.5 w-3/4" />
                <Skeleton className="h-3.5 w-2/3" />
                <Skeleton className="h-3.5 w-1/2" />
              </div>
              <div className="grid grid-cols-2 gap-x-4">
                <Skeleton className="h-9 w-20" />
                <Skeleton className="h-9 w-12" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
