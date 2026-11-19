import { KpiBandSkeleton, PageHeadingSkeleton } from "@/components/skeletons";
import { Skeleton } from "@/components/ui/skeleton";

/** Mirrors a sector page: heading, figures, chart. */
export default function SectorLoading() {
  return (
    <div className="space-y-8 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading sector…</span>
      <PageHeadingSkeleton />
      <KpiBandSkeleton />
      <Skeleton className="h-[380px] w-full rounded-lg" />
    </div>
  );
}
