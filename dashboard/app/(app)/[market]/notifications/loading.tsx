import { MoverListSkeleton, PageHeadingSkeleton } from "@/components/skeletons";

/** Shown while the notifications page loads the feed and the viewer's lists. */
export default function NotificationsLoading() {
  return (
    <div className="space-y-4 px-4 py-5 sm:px-6" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading notifications…</span>
      <PageHeadingSkeleton />
      <MoverListSkeleton rows={8} />
    </div>
  );
}
