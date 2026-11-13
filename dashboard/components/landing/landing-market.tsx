"use client";

import { createContext, useContext, useState, useSyncExternalStore, type ReactNode } from "react";

export type LandingMarketKey = "ind" | "us";

const Context = createContext<{ market: LandingMarketKey; setMarket: (m: LandingMarketKey) => void }>({ market: "ind", setMarket: () => {} });

const noSubscribe = () => () => {};
// The page is built once for every visitor, so the visitor's market is guessed in the browser.
// shortcut: any America/* zone reads as the US (Canada and Latin America too); use a country header if that matters.
const guessMarket = (): LandingMarketKey =>
  Intl.DateTimeFormat().resolvedOptions().timeZone?.startsWith("America/") ? "us" : "ind";

/** The India/US choice the hero grid and the ranking bar share, so one switch answers for both. */
export function LandingMarket({ children }: { children: ReactNode }) {
  const guessed = useSyncExternalStore(noSubscribe, guessMarket, () => "ind" as const);
  const [chosen, setMarket] = useState<LandingMarketKey | null>(null);
  return <Context.Provider value={{ market: chosen ?? guessed, setMarket }}>{children}</Context.Provider>;
}

export const useLandingMarket = () => useContext(Context);
