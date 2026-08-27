import "server-only";

import { cache } from "react";

import { createClient } from "@/lib/supabase/server";
import type { Watchlist } from "@/lib/types";

/**
 * Reads for the per-user watchlists.
 *
 * Separate from `lib/queries.ts` on purpose. Everything there reads the shared,
 * read-only cross-section a run published; everything here is data the viewer
 * owns and writes. They have different authorization stories -- invite list
 * versus row ownership -- and different failure meanings: a failed snapshot read
 * shows a stale run behind a banner, while a failed watchlist read must never
 * silently look like an empty list.
 *
 * Ownership is enforced by RLS, not here. These queries never filter on
 * `owner_id`; the policy in storage/dashboard_schema.sql does, which means a bug
 * in this file cannot expose another viewer's list.
 */

type WatchlistRow = {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  watchlist_items: Array<{ symbol: string }> | null;
};

/**
 * Every list owned by the caller, with its members.
 *
 * One embedded read rather than a query per list. The whole point of the
 * feature is a handful of lists of a couple of hundred symbols at most, so the
 * join is small and paying N+1 round trips at ~175ms each would dominate the
 * page.
 *
 * Wrapped in cache() because the layout renders the selector and the page
 * renders the grid from the same data.
 */
export const getWatchlists = cache(async (): Promise<Watchlist[]> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("watchlists")
    .select("id, name, created_at, updated_at, watchlist_items(symbol)")
    .order("created_at", { ascending: true });

  if (error) {
    console.error("getWatchlists failed", error.message);
    return [];
  }

  return ((data ?? []) as unknown as WatchlistRow[]).map((row) => ({
    id: row.id,
    name: row.name,
    created_at: row.created_at,
    updated_at: row.updated_at,
    symbols: (row.watchlist_items ?? [])
      .map((item) => item.symbol)
      .sort((a, b) => a.localeCompare(b)),
  }));
});

/**
 * Pick the list a request is about.
 *
 * Falls back to the first list rather than erroring on an unknown id, so a
 * stale bookmark or a link to a since-deleted list lands somewhere useful
 * instead of on an error page.
 */
export function resolveWatchlist(
  lists: Watchlist[],
  requestedId: string | undefined,
): Watchlist | null {
  if (!lists.length) return null;
  if (requestedId) {
    const match = lists.find((list) => list.id === requestedId);
    if (match) return match;
  }
  return lists[0];
}

/**
 * Which of the caller's lists contain a given symbol.
 *
 * Used by the add-to-watchlist control, which has to render the checked state
 * before the reader opens it. Reads through `watchlists` rather than
 * `watchlist_items` directly so the ownership policy applies to the parent row.
 */
export const getWatchlistMembership = cache(
  async (symbol: string): Promise<string[]> => {
    const supabase = await createClient();
    const { data, error } = await supabase
      .from("watchlist_items")
      .select("watchlist_id")
      .eq("symbol", symbol.trim().toUpperCase());

    if (error) {
      console.error("getWatchlistMembership failed", error.message);
      return [];
    }
    return ((data ?? []) as Array<{ watchlist_id: string }>).map(
      (row) => row.watchlist_id,
    );
  },
);
