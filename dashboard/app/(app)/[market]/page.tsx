import { Suspense } from "react";
import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { HomeCardSkeleton } from "@/components/home/home-card";
import { BreadthCard } from "@/components/home/breadth-card";
import { ComingUpCard } from "@/components/home/coming-up-card";
import { WatchedProvider } from "@/components/home/quick-watch";
import { DealsCard } from "@/components/home/deals-card";
import { ResultsInCard } from "@/components/home/results-in-card";
import { ShareholdingCard } from "@/components/home/shareholding-card";
import { WatchlistTodayCard } from "@/components/home/watchlist-today-card";
import { LinedUpCard } from "@/components/home/lined-up-card";
import { MoversCard } from "@/components/home/movers-card";
import { PulseCard } from "@/components/home/pulse-card";
import { ResultsSeasonCard } from "@/components/home/results-season-card";
import { SinceCard } from "@/components/home/since-card";
import { StartWatchingCard } from "@/components/home/start-watching-card";
import { withTiming } from "@/lib/home";
import { cardsFor, isScreenerQuery, screenerRedirect } from "@/lib/home.mjs";
import { marketFromSlug, marketPath, type Market } from "@/lib/markets";
import { getWatchedSymbols } from "@/lib/notifications";

const SinceTimed = withTiming("since", SinceCard);
const ResultsInTimed = withTiming("results-in", ResultsInCard);
const ShareholdingTimed = withTiming("shareholding", ShareholdingCard);
const DealsTimed = withTiming("deals", DealsCard);
const ComingUpTimed = withTiming("coming-up", ComingUpCard);
const WatchlistTodayTimed = withTiming("watchlist-today", WatchlistTodayCard);
const PulseTimed = withTiming("pulse", PulseCard);
const MoversTimed = withTiming("movers", MoversCard);
const BreadthTimed = withTiming("breadth", BreadthCard);
const ResultsSeasonTimed = withTiming("results-season", ResultsSeasonCard);
const LinedUpTimed = withTiming("lined-up", LinedUpCard);

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

  // Nothing past the redirect check is awaited here, so the shell and the
  // skeletons flush at once; the watchlist read happens inside the boundary.
  return (
    <Suspense fallback={<HomeSkeleton />}>
      <HomeCards market={market} />
    </Suspense>
  );
}

function HomeSkeleton() {
  return (
    <div className="grid items-start gap-4 px-4 py-5 sm:px-6 lg:grid-cols-2">
      {Array.from({ length: 4 }, (_, index) => (
        <HomeCardSkeleton key={index} />
      ))}
    </div>
  );
}

async function HomeCards({ market }: { market: Market }) {
  const watched = await getWatchedSymbols(market.code);
  const watching = watched.length > 0;
  const cards = cardsFor(market.code, watching);

  const byId: Record<string, React.ReactNode> = {
    since: <SinceTimed market={market} />,
    "results-in": <ResultsInTimed market={market} />,
    shareholding: <ShareholdingTimed market={market} />,
    deals: <DealsTimed market={market} />,
    "coming-up": <ComingUpTimed market={market} />,
    "watchlist-today": <WatchlistTodayTimed market={market} />,
    pulse: <PulseTimed market={market} />,
    movers: <MoversTimed market={market} />,
    breadth: <BreadthTimed market={market} />,
    "results-season": <ResultsSeasonTimed market={market} />,
    "lined-up": <LinedUpTimed market={market} />,
  };

  return (
    <WatchedProvider symbols={watched}>
      <div className="grid items-start gap-4 px-4 py-5 sm:px-6 lg:grid-cols-2">
        {watching ? null : (
          <Suspense fallback={<HomeCardSkeleton className="lg:col-span-2" />}>
            <StartWatchingCard market={market} />
          </Suspense>
        )}
        {cards.map((id) =>
          byId[id] ? (
            <Suspense key={id} fallback={<HomeCardSkeleton />}>
              {byId[id]}
            </Suspense>
          ) : null,
        )}
      </div>
    </WatchedProvider>
  );
}
