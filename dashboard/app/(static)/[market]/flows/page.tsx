import type { Metadata } from "next";

import { BrowserShell } from "@/components/browser-shell";
import { FlowsSkeleton, FlowsView } from "@/components/market/flows-view";
import { SubNav } from "@/components/sub-nav";
import { MARKET_SLUGS, marketFromSlug } from "@/lib/markets";

export const metadata: Metadata = { title: "Investor flows" };

/*
 * A static page: built once per market, copied into the assets directory
 * (scripts/static-pages.mjs), and served by Cloudflare without running the Worker.
 * It is outside the (app) group so no server layout runs for it; the access check,
 * the header and the data are read in the browser (BrowserShell, FlowsView).
 */
export const dynamic = "force-static";
export const dynamicParams = false;

export function generateStaticParams() {
  return MARKET_SLUGS.map((market) => ({ market }));
}

export default async function FlowsPage({ params }: PageProps<"/[market]/flows">) {
  const market = marketFromSlug((await params).market)!;
  // The Market tab's row of pages, as app/(app)/[market]/(market)/layout.tsx draws it; in the
  // skeleton too, so it does not move when the access check lands.
  const subNav = (
    <div className="px-4 pt-5 sm:px-6">
      <SubNav group="Market" market={market} admin={false} />
    </div>
  );

  return (
    <BrowserShell
      slug={market.slug}
      fallback={
        <>
          {subNav}
          <FlowsSkeleton />
        </>
      }
    >
      {subNav}
      <FlowsView />
    </BrowserShell>
  );
}
