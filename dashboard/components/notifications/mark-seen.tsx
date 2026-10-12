"use client";

import { useEffect } from "react";

import { markNotificationsSeen } from "@/app/(app)/[market]/notifications/actions";
import { NOTIFICATIONS_SEEN_EVENT } from "@/components/notifications/bell";

/**
 * Arriving on the notifications page is reading it.
 *
 * An effect rather than a write during render: a server component that
 * mutated while rendering would also fire on a prefetch, marking the feed read
 * for a page the viewer never opened. The window event is how the bell in the
 * header, which the layout rendered before this page existed, learns to clear.
 */
export function MarkNotificationsSeen({ slug }: { slug: string }) {
  useEffect(() => {
    void markNotificationsSeen(slug);
    window.dispatchEvent(new Event(NOTIFICATIONS_SEEN_EVENT));
  }, [slug]);
  return null;
}
