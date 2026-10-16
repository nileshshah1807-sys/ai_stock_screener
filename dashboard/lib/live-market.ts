/**
 * The Market page's movers by index, shared by the server read
 * (`getLiveMarket` in queries.ts) and the browser's refresh of it
 * (components/market/live-movers.tsx). No directive: both sides import it.
 */

/** One stock in a live movers list (storage/live_quotes_schema.sql). */
export type LiveMover = {
  symbol: string;
  company: string | null;
  price: number;
  change_pct: number;
  /** Null for an index member the screener does not rate. */
  investment_rank: number | null;
  rating: string | null;
};

export type LiveIndexMovers = {
  name: string;
  members: number;
  /** The index's own level, where the vendor serves one. */
  level: number | null;
  change_pct: number | null;
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
