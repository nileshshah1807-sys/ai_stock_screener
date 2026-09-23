import { PageHeadingSkeleton, TableSkeleton } from "@/components/skeletons";

export default function NewListingsLoading() {
  return (
    <div className="space-y-4 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading new listings…</span>
      <PageHeadingSkeleton />
      <TableSkeleton rows={10} />
    </div>
  );
}
