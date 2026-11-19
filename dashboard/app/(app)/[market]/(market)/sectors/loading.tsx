import { KpiBandSkeleton, PageHeadingSkeleton } from "@/components/skeletons";
import { Skeleton } from "@/components/ui/skeleton";

/** Mirrors the Sectors page: heading, figures, heatmap. */
export default function SectorsLoading() {
  return (
    <div className="space-y-8 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading sectors…</span>
      <PageHeadingSkeleton />
      <KpiBandSkeleton />
      <Skeleton className="h-[380px] w-full rounded-lg" />
    </div>
  );
}
