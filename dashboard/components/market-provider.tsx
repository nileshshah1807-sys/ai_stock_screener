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

export function MarketProvider({
  market,
  children,
}: {
  market: Market;
  children: React.ReactNode;
}) {
  return (
    <MarketContext.Provider value={market}>{children}</MarketContext.Provider>
  );
}

export function useMarket(): Market {
  return useContext(MarketContext);
}

/** Build a link inside the current market: `useMarketPath()("/movers")`. */
export function useMarketPath(): (path?: string) => string {
  const market = useMarket();
  return (path = "") => marketPath(market.slug, path);
}
