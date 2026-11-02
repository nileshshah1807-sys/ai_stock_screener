import "server-only";

import type { MarketCode } from "@/lib/markets";
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
  const out = new Map<string, { announced_at: string; url: string }[]>();
  if (market !== "NSE" || !symbols.length) return out;
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("company_documents")
    .select("symbol, announced_at, url")
    .eq("market", market)
    .eq("kind", "presentation")
    .in("symbol", symbols)
    .gte("announced_at", since);
  if (error) return out;
  for (const row of data ?? []) {
    const list = out.get(row.symbol) ?? [];
    list.push(row);
    out.set(row.symbol, list);
  }
  return out;
}
