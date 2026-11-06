"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

export type LandingMarketKey = "ind" | "us";

const Context = createContext<{ market: LandingMarketKey; setMarket: (m: LandingMarketKey) => void }>({ market: "ind", setMarket: () => {} });

/** The India/US choice the hero grid and the ranking bar share, so one switch answers for both. */
export function LandingMarket({ children }: { children: ReactNode }) {
  const [market, setMarket] = useState<LandingMarketKey>("ind");
  return <Context.Provider value={{ market, setMarket }}>{children}</Context.Provider>;
}

export const useLandingMarket = () => useContext(Context);
