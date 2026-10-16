/**
 * The Market page's movers by index, shared by the server read
 * (`getLiveMarket` in queries.ts) and the browser's refresh of it
 * (components/market/live-movers.tsx). No directive: both sides import it.
 */

import { tickDirection } from "@/lib/live-quotes.mjs";
import type { Tick } from "@/lib/use-live-quotes";

/** One stock in a live movers list (storage/live_quotes_schema.sql). */
export type LiveMover = {
  symbol: string;
  company: string | null;
  price: number;
  change_pct: number;
  /** Null for an index member the screener does not rate. */
  investment_rank: number | null;
  rating: string | null;
  /** The last move the browser saw; the server never sets one. */
  tick?: Tick | null;
};

export type LiveIndexMovers = {
  name: string;
  members: number;
  /** The index's own level, where the vendor serves one. */
  level: number | null;
  change_pct: number | null;
  /** The level's last move the browser saw. */
  tick?: Tick | null;
  advances: number;
  declines: number;
  unchanged: number;
  gainers: LiveMover[];
  losers: LiveMover[];
};

export type LiveMarket = {
  session: string | null;
  fetched_at: string | null;
  traded_at: string | null;
  indices: LiveIndexMovers[];
};

/** Gainers and losers listed per index. */
export const LIVE_MOVERS_LIMIT = 10;

/** Numeric columns arrive as strings or numbers depending on the driver. */
export function normalizeLiveMarket(data: unknown): LiveMarket | null {
  const raw = data as LiveMarket | null;
  if (!raw?.session || !raw.indices?.length) return null;
  const num = (value: unknown) => (value === null || value === undefined ? null : Number(value));
  const mover = (row: LiveMover): LiveMover => ({
    ...row,
    price: Number(row.price),
    change_pct: Number(row.change_pct),
  });
  return {
    ...raw,
    indices: raw.indices.map((index) => ({
      ...index,
      level: num(index.level),
      change_pct: num(index.change_pct),
      gainers: index.gainers.map(mover),
      losers: index.losers.map(mover),
    })),
  };
}

/**
 * `next`, with each price that moved since `previous` marked up or down.
 *
 * A stock is matched by symbol across every list, not only its own: one that
 * climbs into the top ten was in no list on the last read, and has nothing to
 * compare with, but one that moves from an index's gainers into another's
 * still does. Moves already marked and not repeated keep their mark.
 */
export function withTicks(previous: LiveMarket | null, next: LiveMarket, at: number): LiveMarket {
  if (!previous) return next;
  const mark = (before: number | null | undefined, after: number | null, kept?: Tick | null) => {
    const direction = tickDirection(before, after);
    return direction ? { direction, at } : (kept ?? null);
  };
  const stocks = new Map<string, LiveMover>();
  for (const index of previous.indices) {
    for (const row of [...index.gainers, ...index.losers]) stocks.set(row.symbol, row);
  }
  const levels = new Map(previous.indices.map((index) => [index.name, index]));
  const mover = (row: LiveMover): LiveMover => {
    const old = stocks.get(row.symbol);
    return { ...row, tick: mark(old?.price, row.price, old?.tick) };
  };
  return {
    ...next,
    indices: next.indices.map((index) => {
      const old = levels.get(index.name);
      return {
        ...index,
        tick: mark(old?.level, index.level, old?.tick),
        gainers: index.gainers.map(mover),
        losers: index.losers.map(mover),
      };
    }),
  };
}
