import { AppShell } from "@/components/app-shell";
import { requireAccess } from "@/lib/auth";
import { getLatestRun } from "@/lib/queries";
import { mark, trace } from "@/lib/trace";

/**
 * Shell for every signed-in route.
 *
 * Authorization, the run manifest and the chrome live here rather than in each
 * page because layouts do not re-render on navigation. Moving between Screener,
 * Movers and a stock detail page now re-renders only the page segment; it no
 * longer re-verifies the session, re-reads the run, or rebuilds the nav.
 */
export default async function AppLayout({ children }: LayoutProps<"/">) {
  mark("(app)/layout RENDERED");
  // Issued together rather than in sequence. Each is a round trip to Supabase,
  // which measures ~250ms from any region because the origin sits far from the
  // Cloudflare edge fronting it, so awaiting them one after the other costs a
  // needless ~150ms on every full page load. getLatestRun reveals nothing to an
  // unauthorized viewer -- RLS returns no row -- and requireAccess still
  // redirects before anything renders, because its rejection propagates out of
  // the Promise.all.
  const [viewer, run] = await Promise.all([
    trace("  requireAccess", () => requireAccess()),
    trace("  getLatestRun", () => getLatestRun()),
  ]);

  return (
    <AppShell run={run} viewer={viewer}>
      {children}
    </AppShell>
  );
}
