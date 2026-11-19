import "server-only";

import type { MarketCode } from "@/lib/markets";
import { digest, sharedRead } from "@/lib/home-cache";
import type { Reader } from "@/lib/results";
import { createClient } from "@/lib/supabase/server";
import { readForSymbols } from "@/lib/symbol-scope.mjs";
import { latestOutlooks } from "@/lib/concalls.mjs";

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
  /** bullish | optimistic | neutral | cautious | bearish; null when not read. */
  management_stance?: string | null;
  /** The sentence of the call the stance was read from. */
  management_stance_quote?: string | null;
  outlook_score: number | null;
  highlights: ConcallHighlight[];
  updated_at: string;
  /** When the text the row shows was stored; null until the worker records it. */
  stored_at?: string | null;
};

/** A call with its outlook in the fields a screener run publishes it by. */
export type ConcallWithOutlook = Concall & {
  outlook_detail: Record<string, unknown> | null;
};

const BASE_COLUMNS =
  "symbol, company, quarter, call_date, source, tone_score, tone_percentile, guidance_direction, outlook_score, highlights, updated_at";
// Added after the table first shipped; see getConcalls for what happens
// while a deployment has not re-applied storage/concalls_schema.sql.
const COLUMNS = `${BASE_COLUMNS}, management_stance, management_stance_quote`;

export type ConcallQuery = {
  /** Restrict to these symbols. An empty list matches nothing. */
  symbols?: string[] | null;
  /** Symbol or company containing this text, already through `searchTerm`. */
  search?: string;
  /** Management stances, `bullish` ... `bearish`. Empty means any. */
  stances?: string[];
  limit?: number;
};

/**
 * Calls for one market: newest day first, and within a day the call whose text
 * was stored most recently first, ties by symbol. A table without `stored_at`
 * (not applied yet) or a row where it is null falls back to symbol order.
 */
export async function getConcalls(market: MarketCode, query: ConcallQuery = {}): Promise<Concall[]> {
  const { symbols = null, search = "", stances = [], limit = 150 } = query;
  // `concall_feed` is the same for every viewer, so one cross-instance entry per filter.
  return sharedRead("concalls", market, 300, (db) => readConcalls(market, query, db), [
    symbols ? await digest(symbols) : "all",
    search,
    stances.join(","),
    String(limit),
  ]);
}

async function readConcalls(
  market: MarketCode,
  { symbols = null, search = "", stances = [], limit = 150 }: ConcallQuery,
  db?: Reader,
): Promise<Concall[]> {
  const supabase = db ?? (await createClient());
  const read = (columns: string, byStoredAt = false) =>
    readForSymbols<Concall>(symbols, limit, (pushed, from, to) => {
      let query = supabase.from("concall_feed").select(columns).eq("market", market);
      if (pushed) query = query.in("symbol", pushed);
      if (search) query = query.or(`symbol.ilike.*${search}*,company.ilike.*${search}*`);
      if (stances.length) query = query.in("management_stance", stances);
      query = query.order("call_date", { ascending: false });
      if (byStoredAt) query = query.order("stored_at", { ascending: false, nullsFirst: false });
      return query.order("symbol", { ascending: true }).range(from, to);
    });
  let { rows, error } = await read(`${COLUMNS}, stored_at`, true);
  // Without the stored_at column yet: the same calls, in symbol order within a day.
  if (error) ({ rows, error } = await read(COLUMNS));
  if (error) {
    // A table without the stance columns still has every call; the page
    // shows them without a stance instead of showing nothing.
    ({ rows, error } = await read(BASE_COLUMNS));
  }
  if (error) {
    if (db) throw new Error(String(error));
    console.error("getConcalls failed", error);
  }
  return rows;
}

/**
 * A company's newest call with its full outlook, or null.
 *
 * For the stock page, which shows it when it is newer than the call the
 * published run scored. Null on any failure -- a missing table, or one
 * without the `outlook_detail` column yet -- and the page then shows the
 * run's own call, as it did before this existed.
 */
export async function getLatestConcall(
  market: MarketCode,
  symbol: string,
): Promise<ConcallWithOutlook | null> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("concall_feed")
    .select(`${COLUMNS}, outlook_detail`)
    .eq("market", market)
    .eq("symbol", symbol)
    .order("call_date", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) {
    console.error("getLatestConcall failed", error.message);
    return null;
  }
  return (data as unknown as ConcallWithOutlook | null) ?? null;
}

const OUTLOOK_PAGE = 1000;

/**
 * Each company's latest call outlook since `since`, by symbol (`latestOutlooks`).
 * Through `db`'s `from`, so it reads D1 wherever TABLE_BACKEND has moved
 * `concall_feed` there. Throws on a failed read, so nothing caches it.
 */
export async function readCallOutlooks(db: Reader, market: MarketCode, since: string): Promise<Record<string, number>> {
  const feed: { symbol: unknown; outlook_score: unknown }[] = [];
  for (let from = 0; ; from += OUTLOOK_PAGE) {
    const { data, error } = await db
      .from("concall_feed")
      .select("symbol, call_date, outlook_score")
      .eq("market", market)
      .gte("call_date", since)
      .not("outlook_score", "is", null)
      .order("call_date", { ascending: false })
      .order("symbol", { ascending: true })
      .range(from, from + OUTLOOK_PAGE - 1);
    if (error) throw new Error(error.message);
    const page = (data ?? []) as unknown as { symbol: unknown; outlook_score: unknown }[];
    feed.push(...page);
    if (page.length < OUTLOOK_PAGE) return latestOutlooks(feed);
  }
}

/** `readCallOutlooks` for the browser's score preview (`/api/live?kind=calls`), one shared read per market and day. */
export async function getCallOutlooks(market: MarketCode, since: string): Promise<Record<string, number>> {
  return sharedRead("call-outlooks", market, 300, async (db) => readCallOutlooks(db ?? (await createClient()), market, since), [since]);
}
