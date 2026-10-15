import { PageHeadingSkeleton, PanelSkeleton, TableSkeleton } from "@/components/skeletons";

/** Shown while a ranking is priced forward: tiles, the chart, then holdings. */
export default function ReturnsLoading() {
  return (
    <div className="space-y-5 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading returns…</span>
      <PageHeadingSkeleton />
      <PanelSkeleton />
      <TableSkeleton rows={10} />
    </div>
  );
}
