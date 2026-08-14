import { PageHeadingSkeleton, PanelSkeleton, TableSkeleton } from "@/components/skeletons";

/** Shown while the run-health page loads its manifest and recent-run history. */
export default function HealthLoading() {
  return (
    <div className="space-y-4 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading run health…</span>
      <PageHeadingSkeleton />
      <div className="grid gap-4 lg:grid-cols-2">
        <PanelSkeleton lines={5} />
        <PanelSkeleton lines={4} />
      </div>
      <TableSkeleton rows={8} />
    </div>
  );
}
