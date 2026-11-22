import { PageHeadingSkeleton } from "@/components/skeletons";
import { Skeleton } from "@/components/ui/skeleton";

/** Mirrors the Flows page: heading, daily flows, sector table, deals. */
export default function FlowsLoading() {
  return (
    <div className="space-y-8 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading investor flows…</span>
      <PageHeadingSkeleton />
      <Skeleton className="h-[230px] w-full rounded-lg" />
      <Skeleton className="h-[560px] w-full rounded-lg" />
    </div>
  );
}
