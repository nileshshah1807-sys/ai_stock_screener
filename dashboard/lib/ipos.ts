import "server-only";

import { readLiveObject, readLiveRows } from "@/lib/live-objects";
import type { MarketCode } from "@/lib/markets";

/** One category of the book: shares reserved, shares bid and the ratio (null when none were reserved). */
export type BookCategory = { category: string; offered: number | null; bid: number | null; times: number | null };

/** An NSE issue as workers/ipos.py writes it to `live/NSE/ipos.json`. */
export type Ipo = {
  symbol: string;
  company: string | null;
  board: "Mainboard" | "SME" | null;
  open_date: string | null;
  close_date: string | null;
  listing_date: string | null;
  price_low: number | null;
  price_high: number | null;
  issue_price: number | null;
  lot_size: number | null;
  face_value: number | null;
  book_shares: number | null;
  registrar: string | null;
  rhp_url: string | null;
  subscription: BookCategory[] | null;
  subscription_total: number | null;
  subscription_as_of: string | null;
  listing_open: number | null;
  listing_close: number | null;
  gmp: number | null;
  gmp_pct: number | null;
  gmp_peak: number | null;
  gmp_as_of: string | null;
  /** The restated figures the GMP tracker prints from the prospectus, in `unit`; a blank is null. */
  financials: {
    basis: string | null;
    unit: string | null;
    periods: (string | null)[];
    rows: { label: string; values: (number | null)[] }[];
  } | null;
  /** The RHP's competitive strengths as the tracker prints them; [] when it prints none, null before it is read. */
  strengths: { title: string | null; text: string | null }[] | null;
};

/**
 * Every issue the worker keeps (bidding, upcoming, awaiting listing, listed within
 * a year), or null when the object is absent: the step is off or has not run. The
 * (app) layout has checked the viewer's access; NSE only.
 */
export async function getIpos(market: MarketCode): Promise<Ipo[] | null> {
  if (market !== "NSE") return null;
  return (await readLiveObject(market, "ipos")) as Ipo[] | null;
}

/** A heading of the RHP's Risk Factors chapter: its first sentence, and the rest. */
export type RiskFactor = { title: string; text: string | null };

/** One issue's RHP risk factors, from its own object (`live/NSE/ipo-risks/{symbol}.json`); null before they are read. */
export async function getRiskFactors(market: MarketCode, symbol: string): Promise<RiskFactor[] | null> {
  if (market !== "NSE") return null;
  return (await readLiveRows(market, `ipo-risks/${symbol}`)) as RiskFactor[] | null;
}

/** Today's price for each of `symbols` that the live quotes object holds. */
export async function getPricesNow(market: MarketCode, symbols: string[]): Promise<Map<string, number>> {
  const wanted = new Set(symbols);
  const quotes = (await readLiveObject(market, "quotes")) ?? [];
  const prices = new Map<string, number>();
  for (const quote of quotes) {
    const price = Number(quote.price);
    if (quote.kind !== "index" && wanted.has(String(quote.symbol)) && Number.isFinite(price) && price > 0) {
      prices.set(String(quote.symbol), price);
    }
  }
  return prices;
}
