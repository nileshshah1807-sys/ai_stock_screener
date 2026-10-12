import "server-only";

import type { MarketCode } from "@/lib/markets";
import { createClient } from "@/lib/supabase/server";

/**
 * Reads for the Concalls page.
 *
 * `concall_feed` is shared read-model data any invited viewer may read, one
 * row per earnings call, written by workers/concall_feed.py. The read degrades
 * to an empty list: the table arrives with a migration
 * (storage/concalls_schema.sql) that may be applied after this code deploys.
 */

export type ConcallHighlight = {
  text: string;
  tone: "positive" | "negative";
  /** The sentence of the call the highlight was read from. */
  quote: string;
};

export type Concall = {
  symbol: string;
  company: string | null;
  /** The quarter end the call explains. */
  quarter: string;
  /** The day the call was held. */
  call_date: string;
  /** `recording` until the company files its transcript, then `transcript`. */
  source: "recording" | "transcript";
  tone_score: number | null;
  /** Where the tone stands among the season's calls, 0-100; null when unscored. */
  tone_percentile: number | null;
  guidance_direction: string | null;
  outlook_score: number | null;
  highlights: ConcallHighlight[];
  updated_at: string;
};

const COLUMNS =
  "symbol, company, quarter, call_date, source, tone_score, tone_percentile, guidance_direction, outlook_score, highlights, updated_at";

export type ConcallQuery = {
  /** Restrict to these symbols. An empty list matches nothing. */
  symbols?: string[] | null;
  /** Calls read from a recording only: the ones no transcript exists for yet. */
  recordingOnly?: boolean;
  limit?: number;
};

/** Calls for one market, newest first. */
export async function getConcalls(
  market: MarketCode,
  { symbols = null, recordingOnly = false, limit = 150 }: ConcallQuery = {},
): Promise<Concall[]> {
  if (symbols && symbols.length === 0) return [];
  const supabase = await createClient();
  let query = supabase.from("concall_feed").select(COLUMNS).eq("market", market);
  if (symbols) query = query.in("symbol", symbols);
  if (recordingOnly) query = query.eq("source", "recording");
  const { data, error } = await query
    .order("call_date", { ascending: false })
    .order("symbol", { ascending: true })
    .limit(limit);
  if (error) {
    console.error("getConcalls failed", error.message);
    return [];
  }
  return (data as unknown as Concall[]) ?? [];
}
