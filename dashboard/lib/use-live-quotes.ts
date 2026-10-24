"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import { createClient } from "@/lib/supabase/client";
import { MIN_POLL_MS, nextPollDelay, tickDirection } from "@/lib/live-quotes.mjs";
import type { MarketCode } from "@/lib/markets";

/** Which way a price last moved in this tab, and when the tab saw it. */
export type Tick = { direction: "up" | "down"; at: number };

/** One stock's latest quote, as the grid and the stock page read it. */
export type LiveQuote = {
  symbol: string;
  price: number;
  change_pct: number | null;
  volume: number | null;
  traded_at: string;
  session: string;
  fetched_at: string;
  /**
   * The price ratios at this quote (`live_valuation`, storage/
   * valuation_basis_schema.sql); null for an index, a stock with no stored
   * basis, or a quote withheld as a change of unit.
   */
  market_cap: number | null;
  pe_ratio: number | null;
  pb_ratio: number | null;
  ev_ebitda: number | null;
  /** The last move this tab saw, kept until the next one replaces it. */
  tick: Tick | null;
};

/** The ratios a quote carries, for components that show one. */
export type LiveRatioKey = "market_cap" | "pe_ratio" | "pb_ratio" | "ev_ebitda";
const RATIOS: readonly LiveRatioKey[] = ["market_cap", "pe_ratio", "pb_ratio", "ev_ebitda"];

const QUOTE_COLUMNS = "symbol,price,change_pct,volume,traded_at,session,fetched_at";
// Stocks are read from the view, which is live_quotes with the ratios beside.
const SOURCES = {
  stock: { table: "live_valuation", columns: `${QUOTE_COLUMNS},${RATIOS.join(",")}` },
  index: { table: "live_quotes", columns: QUOTE_COLUMNS },
} as const;

const num = (value: unknown) => (value === null || value === undefined ? null : Number(value));

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

/** A stock, or an index level stored under the index's name. */
export type QuoteKind = "stock" | "index";

const keyOf = (market: MarketCode, symbol: string, kind: QuoteKind = "stock") =>
  `${market}:${kind}:${symbol}`;

function publish() {
  version += 1;
  for (const listener of listeners) listener();
}

/*
 * Every component that asks in the same tick shares one request: a page of
 * result cards, each asking for its own stock, makes one read, not one per
 * card.
 */
type Batch = { symbols: Set<string>; done: Promise<void> };
const batches = new Map<string, Batch>();

async function read(market: MarketCode, kind: QuoteKind, symbols: string[]): Promise<void> {
  const source = SOURCES[kind];
  let request = createClient()
    .from(source.table)
    .select(source.columns)
    .eq("market", market)
    .in("symbol", symbols);
  if (kind === "index") request = request.eq("kind", kind);
  const { data, error } = await request;
  // A failed read leaves the close on screen; the next poll tries again.
  if (error || !data) return;
  const readAt = Date.now();
  for (const row of data as unknown as LiveQuote[]) {
    const key = keyOf(market, row.symbol, kind);
    const before = quotes.get(key);
    const price = Number(row.price);
    const direction = tickDirection(before?.price, price);
    quotes.set(key, {
      ...row,
      price,
      change_pct: num(row.change_pct),
      volume: num(row.volume),
      market_cap: num(row.market_cap),
      pe_ratio: num(row.pe_ratio),
      pb_ratio: num(row.pb_ratio),
      ev_ebitda: num(row.ev_ebitda),
      tick: direction ? { direction, at: readAt } : (before?.tick ?? null),
    });
  }
  publish();
}

function load(
  market: MarketCode,
  symbols: readonly string[],
  kind: QuoteKind,
): Promise<void> {
  const now = Date.now();
  const due = symbols.filter(
    (symbol) => now - (askedAt.get(keyOf(market, symbol, kind)) ?? 0) >= MIN_POLL_MS,
  );
  if (!due.length) return Promise.resolve();
  for (const symbol of due) askedAt.set(keyOf(market, symbol, kind), now);

  const batchKey = `${market}:${kind}`;
  const open = batches.get(batchKey);
  if (open) {
    for (const symbol of due) open.symbols.add(symbol);
    return open.done;
  }
  const batch: Batch = { symbols: new Set(due), done: Promise.resolve() };
  batch.done = Promise.resolve().then(() => {
    batches.delete(batchKey);
    return read(market, kind, [...batch.symbols]);
  });
  batches.set(batchKey, batch);
  return batch.done;
}

function newestFetch(
  market: MarketCode,
  symbols: readonly string[],
  kind: QuoteKind,
): string | null {
  let newest: string | null = null;
  for (const symbol of symbols) {
    const fetched = quotes.get(keyOf(market, symbol, kind))?.fetched_at;
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
 * With `kind` "index", `symbols` are index names and the quote is the level.
 *
 * Runs after the page has rendered and never blocks it. Polls once per worker
 * run (see `nextPollDelay`), not at all while the tab is hidden, and once on
 * return to it.
 */
export function useLiveQuotes(
  market: MarketCode | null,
  symbols: readonly string[],
  kind: QuoteKind = "stock",
): (symbol: string) => LiveQuote | null {
  useSyncExternalStore(subscribe, () => version, () => 0);
  // Index names have spaces and ampersands but no newline.
  const key = symbols.join("\n");

  useEffect(() => {
    if (!market || !key) return;
    const list = key.split("\n");
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const tick = async () => {
      clearTimeout(timer);
      if (document.visibilityState !== "visible") return;
      await load(market, list, kind);
      if (stopped) return;
      // A visibility tick and a timer tick can both reach here; keep one loop.
      clearTimeout(timer);
      timer = setTimeout(tick, nextPollDelay(newestFetch(market, list, kind), Date.now()));
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
  }, [market, key, kind]);

  return (symbol) => (market ? (quotes.get(keyOf(market, symbol, kind)) ?? null) : null);
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
