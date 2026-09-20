import { notFound } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { requireAccess } from "@/lib/auth";
import { marketFromSlug } from "@/lib/markets";
import { getLatestRun } from "@/lib/queries";
import { mark, trace } from "@/lib/trace";

/**
 * Market segment: validates the `[market]` param and renders the chrome.
 *
 * Every route below this is scoped to one market, and this is the single place
 * that decides which. An unrecognised segment 404s rather than falling back to
 * NSE -- serving Indian rows under `/nyse` would be worse than a missing page,
 * because nothing on screen would say which market the reader was looking at.
 *
 * The run manifest is read here rather than in each page for the same reason
 * it always was: layouts do not re-render on navigation, so moving between the
 * screener, Movers and a stock page re-renders only the page segment. It is
 * now per-market, which is correct -- the two markets publish separate runs
 * with separate dates and separate model versions.
 */
export default async function MarketLayout({
  params,
  children,
}: LayoutProps<"/[market]">) {
  mark("[market]/layout RENDERED");
  const { market: slug } = await params;
  const market = marketFromSlug(slug);
  if (!market) notFound();

  // The parent layout already verified access, and getViewer is wrapped in
  // React's cache(), so this resolves from that render's cache rather than
  // spending a second session round trip.
  const [viewer, run] = await Promise.all([
    trace("  requireAccess", () => requireAccess()),
    trace("  getLatestRun", () => getLatestRun(market.code)),
  ]);

  return (
    <AppShell run={run} viewer={viewer} market={market}>
      {children}
    </AppShell>
  );
}
