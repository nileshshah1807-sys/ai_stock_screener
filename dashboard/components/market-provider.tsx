"use client";

import { createContext, useContext } from "react";

import { DEFAULT_MARKET, marketPath, type Market } from "@/lib/markets";

/**
 * The market the current page is showing, for client components.
 *
 * Server components already have the market in scope -- the `[market]` layout
 * resolved it from the route param and every page below reads it from there.
 * Client components do not, and several of them build links to other pages:
 * the grid's rows link to stock pages, the summary tiles link to filtered
 * views, the export link builds an API URL.
 *
 * Threading a `market` prop through each of them would work, but it would
 * spread one fact across a dozen signatures and the compiler would not catch a
 * site that forgot it -- a missing market in a link is a broken URL at runtime,
 * not a type error. A context set once by the shell cannot be forgotten.
 */
const MarketContext = createContext<Market>(DEFAULT_MARKET);
// Whether this viewer may see buy/sell ratings (lib/ratings.mjs). The server
// already redacted them; this only hides the controls that would be empty.
const ShowRatingsContext = createContext(false);

/**
 * The date of the market's latest published run, or null before the first.
 * It names which universe the page is showing, so a client cache of
 * universe-wide data can be keyed on it (see lib/stock-directory.ts).
 */
const RunDateContext = createContext<string | null>(null);

export function MarketProvider({
  market,
  runDate,
  showRatings,
  children,
}: {
  market: Market;
  runDate: string | null;
  showRatings: boolean;
  children: React.ReactNode;
}) {
  return (
    <MarketContext.Provider value={market}>
      <RunDateContext.Provider value={runDate}>
        <ShowRatingsContext.Provider value={showRatings}>{children}</ShowRatingsContext.Provider>
      </RunDateContext.Provider>
    </MarketContext.Provider>
  );
}

export function useMarket(): Market {
  return useContext(MarketContext);
}

export function useRunDate(): string | null {
  return useContext(RunDateContext);
}

export function useShowRatings(): boolean {
  return useContext(ShowRatingsContext);
}

/** Build a link inside the current market: `useMarketPath()("/movers")`. */
export function useMarketPath(): (path?: string) => string {
  const market = useMarket();
  return (path = "") => marketPath(market.slug, path);
}
