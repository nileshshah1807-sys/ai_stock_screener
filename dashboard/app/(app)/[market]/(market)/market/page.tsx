import { Suspense } from "react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { MarketDayNotice } from "@/components/market-day-notice";
import { LiveMovers, LiveMoversSkeleton } from "@/components/market/live-movers";
import { toSearchParams } from "@/lib/filters";
import { marketFromSlug, marketPath, type Market } from "@/lib/markets";
import { getLiveMarket } from "@/lib/queries";

export const metadata: Metadata = { title: "Today’s movers" };
export const dynamic = "force-dynamic";

/** Query keys that belonged to the breadth charts when they shared this page. */
const BREADTH_KEYS = ["sector", "industry", "list", "range", "unit"];

/**
 * The Market tab's first page: today's movers within each index, from the
 * five-minute quotes (components/market/live-movers.tsx). Sectors and breadth
 * are the tab's other pages ((market)/layout.tsx).
 */
export default async function MarketPage({ params, searchParams }: PageProps<"/[market]/market">) {
  const market = marketFromSlug((await params).market)!;
  const query = await searchParams;
  // Breadth lived here until it got its own page; a saved or shared link follows it there.
  if (BREADTH_KEYS.some((key) => key in query)) {
    redirect(`${marketPath(market.slug, "/breadth")}?${toSearchParams(query).toString()}`);
  }

  return (
    <div className="space-y-6 px-4 py-5 sm:px-6">
      <MarketDayNotice />
      {/* Streamed, so the page never waits on the read: the skeleton holds
          its place until it lands. */}
      <Suspense fallback={<LiveMoversSkeleton />}>
        <LiveMoversSection market={market} />
      </Suspense>
    </div>
  );
}

/** Today's movers, read on the server and kept current in the browser. */
async function LiveMoversSection({ market }: { market: Market }) {
  const { live, failed } = await getLiveMarket(market.code);
  return <LiveMovers market={market} initial={live} failed={failed} />;
}
