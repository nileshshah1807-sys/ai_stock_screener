import "server-only";

import type { MarketCode } from "@/lib/markets";
import { digest, sharedRead } from "@/lib/home-cache";
import type { Reader } from "@/lib/results";
import { createClient } from "@/lib/supabase/server";

/**
 * Presentations of these symbols from `since` on, by symbol, for the Results
 * cards (company_documents, NSE only). A failed read is no links, not an error.
 */
export async function getPresentations(
  market: MarketCode,
  symbols: string[],
  since: string,
): Promise<Map<string, { announced_at: string; url: string }[]>> {
  if (market !== "NSE" || !symbols.length) return new Map();
  // Same for every viewer; a Map does not survive the cache, so it is cached as entries.
  const rows = await sharedRead("presentations", market, 600, (db) => readPresentations(market, symbols, since, db), [
    await digest(symbols),
    since,
  ]);
  const out = new Map<string, { announced_at: string; url: string }[]>();
  for (const row of rows) {
    const list = out.get(row.symbol) ?? [];
    list.push({ announced_at: row.announced_at, url: row.url });
    out.set(row.symbol, list);
  }
  return out;
}

type PresentationRow = { symbol: string; announced_at: string; url: string };

async function readPresentations(market: MarketCode, symbols: string[], since: string, db?: Reader): Promise<PresentationRow[]> {
  const supabase = db ?? (await createClient());
  const { data, error } = await supabase
    .from("company_documents")
    .select("symbol, announced_at, url")
    .eq("market", market)
    .eq("kind", "presentation")
    .in("symbol", symbols)
    .gte("announced_at", since)
    // PostgREST returns at most 1,000 rows; newest first so a cut drops the oldest, not today's.
    .order("announced_at", { ascending: false })
    .limit(1000);
  if (error) {
    if (db) throw new Error(error.message);
    return [];
  }
  return (data ?? []) as PresentationRow[];
}
