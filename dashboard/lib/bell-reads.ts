import type { SupabaseClient } from "@supabase/supabase-js";

import type { MarketCode } from "@/lib/markets";
import { bellState } from "@/lib/notifications.mjs";
import { readForSymbols } from "@/lib/symbol-scope.mjs";

/**
 * The bell's and feed's queries, on whichever client the caller has: the server's
 * (lib/notifications.ts, with its caches) or the browser's (the static pages' shell,
 * components/browser-shell.tsx). Both read as the viewer, so RLS decides.
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

export type EventQuery = {
  /** Restrict to these symbols. An empty list matches nothing. */
  symbols?: string[] | null;
  /** Restrict to these kinds. Empty means every kind. */
  kinds?: string[];
  limit?: number;
};

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

const EVENT_COLUMNS = "id, symbol, company, kind, event_key, occurred_at, detected_at, detail";

/** Events for one market, newest first. Baselines are never returned. */
export async function queryEvents(
  db: SupabaseClient,
  market: MarketCode,
  { symbols = null, kinds = [], limit = 200 }: EventQuery,
): Promise<{ rows: MarketEvent[]; error: string | null }> {
  return readForSymbols<MarketEvent>(symbols, limit, (pushed, from, to) => {
    let query = db.from("market_events").select(EVENT_COLUMNS).eq("market", market).eq("baseline", false);
    if (pushed) query = query.in("symbol", pushed);
    if (kinds.length) query = query.in("kind", kinds);
    return query.order("occurred_at", { ascending: false }).order("id", { ascending: false }).range(from, to);
  });
}

/** When the viewer last opened this market's feed, or null if never. */
export async function querySeenAt(db: SupabaseClient, market: MarketCode): Promise<string | null> {
  // RLS returns only the caller's row, so there is no owner filter to get wrong.
  const { data, error } = await db.from("notification_reads").select("seen_at").eq("market", market).maybeSingle();
  if (error) {
    console.error("seen_at read failed", error.message);
    return null;
  }
  return (data as { seen_at: string } | null)?.seen_at ?? null;
}

export async function countUnread(
  db: SupabaseClient,
  market: MarketCode,
  seenAt: string | null,
  symbols: string[] | null,
): Promise<number> {
  if (symbols && symbols.length === 0) return 0;
  let query = db
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

/** The bell's state read straight from one client (the browser shell); every read degrades to nothing. */
export function readBellState(db: SupabaseClient, market: MarketCode): Promise<BellState> {
  return bellState({
    seenAt: () => querySeenAt(db, market),
    watched: async () => {
      const { data } = await db.from("watchlists").select("watchlist_items(symbol)").eq("market", market);
      const rows = (data ?? []) as unknown as { watchlist_items: { symbol: string }[] | null }[];
      return [...new Set(rows.flatMap((row) => (row.watchlist_items ?? []).map((item) => item.symbol)))];
    },
    events: async (query) => (await queryEvents(db, market, query)).rows,
    unread: (seenAt, symbols) => countUnread(db, market, seenAt, symbols),
  }).catch((): BellState => ({ events: [], unread: 0, seenAt: null, watching: false })) as Promise<BellState>;
}
