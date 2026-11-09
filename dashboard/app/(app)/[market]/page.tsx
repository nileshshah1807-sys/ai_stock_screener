import { Suspense } from "react";
import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { HomeCardSkeleton } from "@/components/home/home-card";
import { ComingUpCard } from "@/components/home/coming-up-card";
import { SinceCard } from "@/components/home/since-card";
import { cardsFor, isScreenerQuery, screenerRedirect } from "@/lib/home.mjs";
import { marketFromSlug, marketPath } from "@/lib/markets";
import { getWatchedSymbols } from "@/lib/notifications";

export const metadata: Metadata = { title: "Home" };
export const dynamic = "force-dynamic";

/**
 * Home: what changed for the viewer, then the market. Each card is its own
 * Suspense boundary, so the page paints at once and cards arrive as their
 * reads finish. The screener used to live here; a link that still carries
 * filters (`/ind?rating=BUY`) is sent to its new path with them.
 */
export default async function HomePage({
  params,
  searchParams,
}: PageProps<"/[market]">) {
  const market = marketFromSlug((await params).market);
  if (!market) notFound();
  const query = await searchParams;
  if (isScreenerQuery(query)) redirect(screenerRedirect(marketPath(market.slug), query));

  const watching = (await getWatchedSymbols(market.code)).length > 0;
  const cards = cardsFor(market.code, watching);

  const byId: Record<string, React.ReactNode> = {
    since: <SinceCard market={market} />,
    "coming-up": <ComingUpCard market={market} />,
  };

  return (
    <div className="grid gap-4 px-4 py-5 sm:px-6 lg:grid-cols-2">
      {cards.map((id) =>
        byId[id] ? (
          <Suspense key={id} fallback={<HomeCardSkeleton />}>
            {byId[id]}
          </Suspense>
        ) : null,
      )}
    </div>
  );
}
