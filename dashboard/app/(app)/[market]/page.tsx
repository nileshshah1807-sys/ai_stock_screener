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
import { HERO_CARDS, STRIP_CARDS, cardsFor, columnCards, isScreenerQuery, screenerRedirect } from "@/lib/home.mjs";
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
    <div className="space-y-4 px-4 py-5 sm:px-6">
      <HomeCardSkeleton rows={3} className="min-h-64" />
      <div className="gap-4 lg:columns-2 xl:columns-3">
        {Array.from({ length: 3 }, (_, index) => (
          <div key={index} className="mb-4 break-inside-avoid">
            <HomeCardSkeleton />
          </div>
        ))}
      </div>
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
  const shown = (ids: string[]) =>
    ids.map((id) => (
      <Suspense key={id} fallback={<HomeCardSkeleton rows={3} className={HERO_CARDS.includes(id) ? "min-h-64" : "min-h-40"} />}>
        {byId[id]}
      </Suspense>
    ));

  // The market band and the dated strip are full width; everything else flows
  // in columns, so a card is as tall as what it holds and never stretches to a
  // neighbour. Cards that have nothing to say render nothing and leave no hole.
  return (
    <WatchedProvider symbols={watched}>
      <div className="space-y-4 px-4 py-5 sm:px-6">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
          {shown(cards.filter((id) => HERO_CARDS.includes(id)))}
        </div>
        {shown(cards.filter((id) => STRIP_CARDS.includes(id)))}
        {watching ? null : (
          <Suspense fallback={<HomeCardSkeleton rows={2} />}>
            <StartWatchingCard market={market} />
          </Suspense>
        )}
        <div className="gap-4 lg:columns-2 xl:columns-3">
          {columnCards(cards).map((id) => (
            <div key={id} className="mb-4 break-inside-avoid">
              <Suspense fallback={<HomeCardSkeleton />}>{byId[id]}</Suspense>
            </div>
          ))}
        </div>
      </div>
    </WatchedProvider>
  );
}
