"use client";

import { useLinkStatus } from "next/link";

/**
 * Marks a navigation in flight, for CSS to react to.
 *
 * A sort, page or filter change on the screener re-renders only the page
 * segment, which has no loading boundary of its own: measured at ~760ms, the
 * grid sat unchanged for the whole server round trip and the click read as
 * ignored. Every control that starts one of those navigations renders this
 * while it is pending, and the screener's container dims its rows on
 * `:has([data-nav-pending])` (globals.css). One CSS rule, rather than a
 * context threaded through six controls, because the controls live in two
 * different segments -- the filter chrome in the layout, the grid in the page.
 */
export function PendingMarker({ pending }: { pending: boolean }) {
  return pending ? <span data-nav-pending hidden /> : null;
}

/** The same, for a `<Link>`: must be rendered inside one. */
export function LinkPending() {
  const { pending } = useLinkStatus();
  return <PendingMarker pending={pending} />;
}
