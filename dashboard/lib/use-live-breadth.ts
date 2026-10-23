"use client";

import { useEffect, useRef, useState } from "react";

import { createClient } from "@/lib/supabase/client";
import { nextPollDelay, tickDirection } from "@/lib/live-quotes.mjs";
import type { MarketCode } from "@/lib/markets";
import type { Tick } from "@/lib/use-live-quotes";

/**
 * Today's breadth counts from the five-minute quotes (`live_breadth` in
 * storage/market_breadth_schema.sql), in the keys of a published breadth row:
 * "e50" of "e50d", "hi" and "lo" of "hld", "bb" of "bbd".
 */
export type LiveBreadth = {
  session: string;
  fetched_at: string;
  traded_at: string;
  /** The session the levels follow; the counts are for a later one. */
  as_of: string | null;
  counts: Record<string, number> | null;
  /** Each metric's last move this tab saw, by its share, for the flash. */
  ticks: Record<string, Tick>;
};

/** The denominator each live metric is counted out of. */
export const LIVE_DENOMINATORS: Record<string, string> = {
  e20: "e20d",
  e50: "e50d",
  e100: "e100d",
  e200: "e200d",
  hi: "hld",
  lo: "hld",
  bb: "bbd",
};

type Group = { scope: "market" | "sector" | "industry"; name: string };

function share(counts: Record<string, number> | null | undefined, key: string) {
  const total = counts?.[LIVE_DENOMINATORS[key]];
  const count = counts?.[key];
  return total && count !== undefined ? count / total : undefined;
}

/**
 * Live breadth for one group, asked for once per worker run while the tab is
 * visible -- the movers' rhythm. The Market page remounts its dashboard per
 * group, so a sector never shows the market's counts.
 */
export function useLiveBreadth(market: MarketCode, group: Group): LiveBreadth | null {
  const [data, setData] = useState<LiveBreadth | null>(null);
  const latest = useRef<LiveBreadth | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const tick = async () => {
      clearTimeout(timer);
      if (document.visibilityState !== "visible") return;
      const { data: fresh, error } = await createClient().rpc("live_breadth", {
        p_market: market,
        p_scope: group.scope,
        p_name: group.name,
      });
      if (stopped) return;
      // A failed read keeps the last counts; the next poll tries again.
      if (!error && fresh) {
        const next = fresh as Omit<LiveBreadth, "ticks">;
        const before = latest.current;
        const at = Date.now();
        const ticks: Record<string, Tick> = { ...(before?.ticks ?? {}) };
        for (const key of Object.keys(LIVE_DENOMINATORS)) {
          const direction = tickDirection(share(before?.counts, key), share(next.counts, key));
          if (direction) ticks[key] = { direction, at };
        }
        latest.current = { ...next, ticks };
        setData(latest.current);
      }
      clearTimeout(timer);
      timer = setTimeout(tick, nextPollDelay(latest.current?.fetched_at ?? null, Date.now()));
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") void tick();
    };

    void tick();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [market, group.scope, group.name]);

  return data;
}
