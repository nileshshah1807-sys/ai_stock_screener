"use client";

import { useEffect, useSyncExternalStore } from "react";

import type { MarketSlug } from "@/lib/markets";
import type { IndexInfo, SearchEntry } from "@/lib/types";

/*
 * Every stock in a market's latest run -- symbol, company, logo domain, rank,
 * rating -- held once per tab and shared by everything that names a stock.
 *
 * It is the ⌘K search index (/api/search-index), which also carries the
 * market's indices for the header search: one request the browser
 * keeps for an hour, so a row that knows only a symbol -- a live mover, a
 * feed event -- can show the same logo, name and rank as the screener without
 * its own query, and without every server read having to join them in.
 *
 * Asked for lazily: the first component that is missing a fact loads it, and
 * a page whose rows already carry everything never does.
 */

type Payload = { entries: SearchEntry[]; indices: IndexInfo[] };

const payloads = new Map<MarketSlug, Promise<Payload>>();
const directories = new Map<MarketSlug, Map<string, SearchEntry>>();
const listeners = new Set<() => void>();

/** The search route's whole answer, fetched at most once per page load. */
function loadPayload(market: MarketSlug): Promise<Payload> {
  const cached = payloads.get(market);
  if (cached) return cached;

  // `v` names the payload's shape: the browser holds an answer for an hour,
  // and one cached before it carried `indices` would list none.
  const promise = fetch(`/api/search-index?market=${market}&v=2`)
    .then((response) => (response.ok ? response.json() : {}))
    .then((payload: Partial<Payload>) => ({
      entries: payload.entries ?? [],
      indices: payload.indices ?? [],
    }))
    .then((payload) => {
      directories.set(market, new Map(payload.entries.map((entry) => [entry.s, entry])));
      for (const listener of listeners) listener();
      return payload;
    })
    .catch(() => {
      // Let a failed load retry on the next request for it rather than
      // caching the failure for the life of the page.
      payloads.delete(market);
      return { entries: [], indices: [] };
    });
  payloads.set(market, promise);
  return promise;
}

/** The market's whole index, fetched at most once per page load. */
export function loadSearchIndex(market: MarketSlug): Promise<SearchEntry[]> {
  return loadPayload(market).then((payload) => payload.entries);
}

/** The market's indices, from the same request as the stocks. */
export function loadIndexDirectory(market: MarketSlug): Promise<IndexInfo[]> {
  return loadPayload(market).then((payload) => payload.indices);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * The directory entry for `symbol`, or null until it has loaded (or when the
 * run does not rate the symbol). Loads only while `wanted`.
 */
export function useStockEntry(
  market: MarketSlug,
  symbol: string,
  wanted: boolean,
): SearchEntry | null {
  const directory = useSyncExternalStore(
    subscribe,
    () => directories.get(market) ?? null,
    () => null,
  );
  useEffect(() => {
    if (wanted && !directories.has(market)) void loadSearchIndex(market);
  }, [market, wanted]);
  return wanted ? (directory?.get(symbol) ?? null) : null;
}
