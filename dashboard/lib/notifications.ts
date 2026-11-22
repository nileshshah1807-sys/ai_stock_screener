import "server-only";

import { cache } from "react";

import { countUnread, queryEvents, querySeenAt, type BellState, type EventQuery, type MarketEvent } from "@/lib/bell-reads";
import { digest, sharedRead } from "@/lib/home-cache";
import type { MarketCode } from "@/lib/markets";
import { createClient } from "@/lib/supabase/server";
import { bellState } from "@/lib/notifications.mjs";
import { getWatchlists } from "@/lib/watchlists";

/**
 * Reads for the notification bell and feed.
 *
 * Two tables with two authorization stories, as with watchlists: `market_events`
 * is shared read-model data any invited viewer may read, and
 * `notification_reads` is the viewer's own row, gated by ownership in RLS.
 *
 * Every read here degrades to "nothing": an empty feed, never seen, zero
 * unread. The tables arrive with a migration (storage/notifications_schema.sql)
 * that may be applied after this code deploys, and a bell that cannot load
 * must not take the header -- which every page renders -- down with it.
 */

export type { BellState, EventQuery, MarketEvent };

/** Events for one market, newest first. Baselines are never returned. */
export async function getEvents(market: MarketCode, query: EventQuery = {}): Promise<MarketEvent[]> {
  const { symbols = null, kinds = [], limit = 200 } = query;
  // `market_events` is the same for every viewer: one cross-instance entry per scope, two minutes old at most.
  return sharedRead(
    "events",
    market,
    120,
    async (db) => {
      const { rows, error } = await queryEvents(db ?? (await createClient()), market, query);
      // Inside the cache a failure must not be kept; read directly, it degrades to what was found.
      if (error && db) throw new Error(error);
      if (error) console.error("getEvents failed", error);
      return rows;
    },
    [symbols ? await digest(symbols) : "all", kinds.join(","), String(limit)],
  );
}

/** When the viewer last opened this market's feed, or null if never. */
export const getSeenAt = cache(async (market: MarketCode): Promise<string | null> => querySeenAt(await createClient(), market));

/** Every symbol on any of the viewer's lists in this market. */
export const getWatchedSymbols = cache(async (market: MarketCode): Promise<string[]> => {
  const lists = await getWatchlists(market);
  return [...new Set(lists.flatMap((list) => list.symbols))];
});

/**
 * What the header's bell shows. Read in the market layout, which does not
 * re-render on navigation, so this costs its three small reads once per market
 * visit rather than once per page.
 */
export const getBellState = cache(
  async (market: MarketCode): Promise<BellState> =>
    (await bellState({
      seenAt: () => getSeenAt(market),
      watched: () => getWatchedSymbols(market),
      events: (query) => getEvents(market, query),
      unread: async (seenAt, symbols) => countUnread(await createClient(), market, seenAt, symbols),
    })) as BellState,
);
