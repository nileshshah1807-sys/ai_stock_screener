"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import { createClient } from "@/lib/supabase/client";
import { MIN_POLL_MS, nextPollDelay } from "@/lib/live-quotes.mjs";
import type { MarketCode } from "@/lib/markets";

/** One stock's latest quote, as the grid and the stock page read it. */
export type LiveQuote = {
  symbol: string;
  price: number;
  change_pct: number | null;
  traded_at: string;
  session: string;
  fetched_at: string;
};

const COLUMNS = "symbol,price,change_pct,traded_at,session,fetched_at";

/*
 * One store for the whole tab, outside React.
 *
 * Quotes outlive the component that asked for them, so a sort, a page change
 * or a step back to the grid shows the live figures already held, with no
 * second request and no flash of the close. A symbol asked for within
 * MIN_POLL_MS is not asked for again, which also folds two components that
 * want the same stock in the same tick -- the stock page's Price and 1D
 * tiles -- into one request.
 */
const quotes = new Map<string, LiveQuote>();
const askedAt = new Map<string, number>();
const listeners = new Set<() => void>();
let version = 0;

const keyOf = (market: MarketCode, symbol: string) => `${market}:${symbol}`;

function publish() {
  version += 1;
  for (const listener of listeners) listener();
}

async function load(market: MarketCode, symbols: readonly string[]): Promise<void> {
  const now = Date.now();
  const due = symbols.filter(
    (symbol) => now - (askedAt.get(keyOf(market, symbol)) ?? 0) >= MIN_POLL_MS,
  );
  if (!due.length) return;
  for (const symbol of due) askedAt.set(keyOf(market, symbol), now);

  const { data, error } = await createClient()
    .from("live_quotes")
    .select(COLUMNS)
    .eq("market", market)
    .eq("kind", "stock")
    .in("symbol", due);
  // A failed read leaves the close on screen; the next poll tries again.
  if (error || !data) return;
  for (const row of data as unknown as LiveQuote[]) {
    quotes.set(keyOf(market, row.symbol), {
      ...row,
      price: Number(row.price),
      change_pct: row.change_pct === null ? null : Number(row.change_pct),
    });
  }
  publish();
}

function newestFetch(market: MarketCode, symbols: readonly string[]): string | null {
  let newest: string | null = null;
  for (const symbol of symbols) {
    const fetched = quotes.get(keyOf(market, symbol))?.fetched_at;
    if (fetched && (!newest || fetched > newest)) newest = fetched;
  }
  return newest;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * The latest quote for each of `symbols`, kept fresh while the tab is visible.
 *
 * Runs after the page has rendered and never blocks it. Polls once per worker
 * run (see `nextPollDelay`), not at all while the tab is hidden, and once on
 * return to it.
 */
export function useLiveQuotes(
  market: MarketCode | null,
  symbols: readonly string[],
): (symbol: string) => LiveQuote | null {
  useSyncExternalStore(subscribe, () => version, () => 0);
  const key = symbols.join(",");

  useEffect(() => {
    if (!market || !key) return;
    const list = key.split(",");
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const tick = async () => {
      clearTimeout(timer);
      if (document.visibilityState !== "visible") return;
      await load(market, list);
      if (stopped) return;
      // A visibility tick and a timer tick can both reach here; keep one loop.
      clearTimeout(timer);
      timer = setTimeout(tick, nextPollDelay(newestFetch(market, list), Date.now()));
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
  }, [market, key]);

  return (symbol) => (market ? (quotes.get(keyOf(market, symbol)) ?? null) : null);
}

/**
 * The time, for "live" versus "as of" and for whether a quote is from today.
 * Read once on mount and every half minute after, so rendering stays pure.
 */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
