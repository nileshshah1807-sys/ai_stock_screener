import "server-only";

import { addDays } from "@/lib/home";
import { monthsBefore } from "@/lib/financials.mjs";
import { decodeSeries } from "@/lib/price-series.mjs";
import type { MarketCode } from "@/lib/markets";
import {
  getPriceCalendar,
  getPriceSeries,
  type BulkBlockDealRow,
  type ShareholdingPatternRow,
} from "@/lib/queries";
import { getQuarterFilings, type QuarterFiling, type ResultFeedEntry } from "@/lib/results";
import { readForSymbols } from "@/lib/symbol-scope.mjs";
import { createClient } from "@/lib/supabase/server";

/*
 * Reads for the Home page's watchlist cards. Every one filters on market and
 * on the viewer's symbols, and degrades to "nothing" so a card that cannot
 * load renders nothing rather than taking the page down.
 */

/** Watched stocks whose result was announced in the last `days`, newest first. */
export async function getRecentResults(market: MarketCode, symbols: string[], since: string, limit = 8) {
  const supabase = await createClient();
  const { rows, error } = await readForSymbols<ResultFeedEntry>(symbols, limit, (pushed, from, to) => {
    let query = supabase
      .from("quarterly_result_feed")
      .select("symbol, period_end, announced_at, company, has_consolidated, has_standalone")
      .eq("market", market)
      .gte("announced_at", since)
      .order("announced_at", { ascending: false });
    if (pushed) query = query.in("symbol", pushed);
    return query.range(from, to);
  });
  if (error) console.error("getRecentResults failed", error);
  return rows;
}

/** The filings a growth rate needs for these results: each quarter and the one a year before. */
export function getResultFilings(market: MarketCode, entries: ResultFeedEntry[]): Promise<QuarterFiling[]> {
  const periods = [...new Set(entries.flatMap((entry) => [entry.period_end, monthsBefore(entry.period_end, 12)]))];
  return getQuarterFilings(market, [...new Set(entries.map((entry) => entry.symbol))], periods);
}

export type ShareholdingFiling = Pick<ShareholdingPatternRow, "period_end" | "promoter" | "fii" | "dii"> & {
  symbol: string;
  company: string | null;
};

/** The last two quarters' stakes for these symbols (a filing a quarter late still has both inside 8 months). */
export async function getRecentShareholding(market: MarketCode, symbols: string[], today: string) {
  const supabase = await createClient();
  const { rows, error } = await readForSymbols<ShareholdingFiling>(symbols, 1000, (pushed, from, to) => {
    let query = supabase
      .from("shareholding_patterns")
      .select("symbol, company, period_end, promoter, fii, dii")
      .eq("market", market)
      .gte("period_end", monthsBefore(today, 8));
    if (pushed) query = query.in("symbol", pushed);
    return query.order("period_end", { ascending: false }).range(from, to);
  });
  if (error) console.error("getRecentShareholding failed", error);
  return rows;
}

export type WatchedDeal = BulkBlockDealRow & { symbol: string };

/** Watched stocks' deals in the last `days`, and the newest deal day of the whole feed (its freshness). */
export async function getRecentDeals(market: MarketCode, symbols: string[], today: string, days = 7) {
  const supabase = await createClient();
  const feed = () => supabase.from("bulk_block_deals").select("deal_date").eq("market", market);
  const [deals, newest] = await Promise.all([
    readForSymbols<WatchedDeal>(symbols, 200, (pushed, from, to) => {
      let query = supabase
        .from("bulk_block_deals")
        .select("symbol, kind, deal_date, client_name, side, quantity, price, remarks")
        .eq("market", market)
        .gte("deal_date", addDays(today, -days));
      if (pushed) query = query.in("symbol", pushed);
      return query.order("deal_date", { ascending: false }).range(from, to);
    }),
    feed().order("deal_date", { ascending: false }).limit(1).maybeSingle(),
  ]);
  if (deals.error) console.error("getRecentDeals failed", deals.error);
  return { deals: deals.rows, newest: (newest.data?.deal_date as string | undefined) ?? null };
}

/** Ascending closes of one stock from its stored price series, or [] when it has none. */
export async function getRecentCloses(market: MarketCode, symbol: string): Promise<number[]> {
  const [row, sessions] = await Promise.all([getPriceSeries(market, symbol), getPriceCalendar(market)]);
  return decodeSeries(row, sessions ?? []).points.map((point) => point.close);
}
