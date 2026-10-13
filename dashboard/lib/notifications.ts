import "server-only";

import { cache } from "react";

import type { MarketCode } from "@/lib/markets";
import { createClient } from "@/lib/supabase/server";
import { readForSymbols } from "@/lib/symbol-scope.mjs";
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

export type MarketEvent = {
  id: number;
  symbol: string;
  company: string | null;
  /** `results` | `transcript`; an unknown kind still renders by name. */
  kind: string;
  event_key: string;
  /** When it happened at the source. */
  occurred_at: string;
  /** When a worker recorded it; unread is measured against this. */
  detected_at: string;
  detail: Record<string, string | null | undefined>;
};

const EVENT_COLUMNS = "id, symbol, company, kind, event_key, occurred_at, detected_at, detail";

export type EventQuery = {
  /** Restrict to these symbols. An empty list matches nothing. */
  symbols?: string[] | null;
  /** Restrict to these kinds. Empty means every kind. */
  kinds?: string[];
  limit?: number;
};

/** Events for one market, newest first. Baselines are never returned. */
export async function getEvents(
  market: MarketCode,
  { symbols = null, kinds = [], limit = 200 }: EventQuery = {},
): Promise<MarketEvent[]> {
  const supabase = await createClient();
  const { rows, error } = await readForSymbols<MarketEvent>(symbols, limit, (pushed, from, to) => {
    let query = supabase
      .from("market_events")
      .select(EVENT_COLUMNS)
      .eq("market", market)
      .eq("baseline", false);
    if (pushed) query = query.in("symbol", pushed);
    if (kinds.length) query = query.in("kind", kinds);
    return query
      .order("occurred_at", { ascending: false })
      .order("id", { ascending: false })
      .range(from, to);
  });
  if (error) console.error("getEvents failed", error);
  return rows;
}

/** When the viewer last opened this market's feed, or null if never. */
export const getSeenAt = cache(async (market: MarketCode): Promise<string | null> => {
  const supabase = await createClient();
  // RLS returns only the caller's row, so there is no owner filter to get wrong.
  const { data, error } = await supabase
    .from("notification_reads")
    .select("seen_at")
    .eq("market", market)
    .maybeSingle();
  if (error) {
    console.error("getSeenAt failed", error.message);
    return null;
  }
  return (data as { seen_at: string } | null)?.seen_at ?? null;
});

async function countUnread(
  market: MarketCode,
  seenAt: string | null,
  symbols: string[] | null,
): Promise<number> {
  if (symbols && symbols.length === 0) return 0;
  const supabase = await createClient();
  let query = supabase
    .from("market_events")
    .select("id", { count: "exact", head: true })
    .eq("market", market)
    .eq("baseline", false);
  if (seenAt) query = query.gt("detected_at", seenAt);
  if (symbols) query = query.in("symbol", symbols);
  const { count, error } = await query;
  if (error) {
    console.error("countUnread failed", error.message);
    return 0;
  }
  return count ?? 0;
}

/** Every symbol on any of the viewer's lists in this market. */
export const getWatchedSymbols = cache(async (market: MarketCode): Promise<string[]> => {
  const lists = await getWatchlists(market);
  return [...new Set(lists.flatMap((list) => list.symbols))];
});

export type BellState = {
  /** The newest few events in the bell's scope. */
  events: MarketEvent[];
  unread: number;
  seenAt: string | null;
  /**
   * Whether the bell is scoped to the viewer's watchlists. It is whenever they
   * have any: in a results season the whole market files hundreds of results a
   * day, and a badge that is always full says nothing.
   */
  watching: boolean;
};

const BELL_EVENTS = 8;

/**
 * What the header's bell shows. Read in the market layout, which does not
 * re-render on navigation, so this costs its three small reads once per market
 * visit rather than once per page.
 */
export const getBellState = cache(async (market: MarketCode): Promise<BellState> => {
  const [seenAt, watched] = await Promise.all([getSeenAt(market), getWatchedSymbols(market)]);
  const symbols = watched.length ? watched : null;
  const [events, unread] = await Promise.all([
    getEvents(market, { symbols, limit: BELL_EVENTS }),
    countUnread(market, seenAt, symbols),
  ]);
  return { events, unread, seenAt, watching: symbols !== null };
});
