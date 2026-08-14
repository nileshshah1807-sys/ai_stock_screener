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
  const viewer = await trace("  requireAccess", () => requireAccess());
  const run = await trace("  getLatestRun", () => getLatestRun());

  return (
    <AppShell run={run} viewer={viewer}>
      {children}
    </AppShell>
  );
}
