import "server-only";

import type { MarketCode } from "@/lib/markets";
import { getLatestRun, getSearchIndex } from "@/lib/queries";
import { createClient } from "@/lib/supabase/server";
import { PUSH_DOWN_MAX, readForSymbols } from "@/lib/symbol-scope.mjs";

/**
 * Reads for the Results page.
 *
 * `quarterly_filings` is the exchange's results filings, parsed once by
 * workers/quarterly_filings.py as companies file them through the evening;
 * the page reads it as the signed-in viewer, so a result is here as soon as
 * the worker has stored it. `quarterly_result_feed` is the same table as one
 * row per company and quarter, which is what the page pages through. Both
 * reads degrade to nothing while storage/quarterly_filings_schema.sql has
 * not been re-applied with the read policy and the view.
 */

export type ResultFeedEntry = {
  symbol: string;
  period_end: string;
  /** When the company first announced the quarter, on either basis. */
  announced_at: string | null;
  company: string | null;
  has_consolidated: boolean;
  has_standalone: boolean;
};

export type QuarterFiling = {
  symbol: string;
  period_end: string;
  is_consolidated: boolean;
  filed_at: string | null;
  viewer_url?: string | null;
  document_url: string | null;
  lines: Record<string, number | null>;
};

/** PostgREST returns at most this many rows per request. */
const READ_WINDOW = 1000;

const FEED_COLUMNS =
  "symbol, period_end, announced_at, company, has_consolidated, has_standalone";
// viewer_url arrived after the table first shipped; see getQuarterFilings.
const FILING_COLUMNS = "symbol, period_end, is_consolidated, filed_at, document_url, lines";

/** The newest of `offered` that anyone has filed for, or null. */
export async function getLatestResultQuarter(
  market: MarketCode,
  offered: string[],
): Promise<string | null> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("quarterly_filings")
    .select("period_end")
    .eq("market", market)
    .in("period_end", offered)
    .order("period_end", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) {
    console.error("getLatestResultQuarter failed", error.message);
    return null;
  }
  return (data?.period_end as string | undefined) ?? null;
}

/** The latest run's company names, by symbol. */
async function runCompanyNames(market: MarketCode): Promise<Map<string, string>> {
  const names = new Map<string, string>();
  const run = await getLatestRun(market);
  if (!run) return names;
  for (const entry of await getSearchIndex(market, run.run_date, run.row_count)) {
    if (entry.c) names.set(entry.s, entry.c);
  }
  return names;
}

export type ResultFeedQuery = {
  quarter: string;
  /** Restrict to these symbols; null for the whole market, empty for nothing. */
  symbols?: string[] | null;
  /** Symbol or company containing this text, already through `searchTerm`. */
  search?: string;
  limit?: number;
};

/**
 * One quarter's results, newest announcement first, with how many there are
 * in all -- or null for the count when the symbol filter is too large to send
 * and the feed was read in windows instead (`readForSymbols`).
 */
export async function getResultFeed(
  market: MarketCode,
  { quarter, symbols = null, search = "", limit = 30 }: ResultFeedQuery,
): Promise<{ entries: ResultFeedEntry[]; total: number | null }> {
  if (symbols && symbols.length === 0) return { entries: [], total: 0 };
  const supabase = await createClient();

  // A filing stored before the company's name was kept with it has none of
  // its own, so a search by name also asks for the symbols the run names so.
  let named: string[] = [];
  if (search) {
    const term = search.toLowerCase();
    named = [...(await runCompanyNames(market))]
      .filter(([, name]) => name.toLowerCase().includes(term))
      .map(([symbol]) => symbol)
      .slice(0, PUSH_DOWN_MAX);
  }

  const query = (count: boolean) => {
    let built = supabase
      .from("quarterly_result_feed")
      .select(FEED_COLUMNS, count ? { count: "exact" } : undefined)
      .eq("market", market)
      .eq("period_end", quarter);
    if (search) {
      const clauses = [`symbol.ilike.*${search}*`, `company.ilike.*${search}*`];
      if (named.length) clauses.push(`symbol.in.(${named.map((s) => `"${s}"`).join(",")})`);
      built = built.or(clauses.join(","));
    }
    return built
      .order("announced_at", { ascending: false, nullsFirst: false })
      .order("symbol", { ascending: true });
  };

  if (!symbols || symbols.length <= PUSH_DOWN_MAX) {
    // One request returns at most READ_WINDOW rows; a longer read goes by windows.
    const entries: ResultFeedEntry[] = [];
    let total: number | null = null;
    for (let from = 0; from < limit; from += READ_WINDOW) {
      let built = query(true);
      if (symbols) built = built.in("symbol", symbols);
      const { data, error, count } = await built.range(from, Math.min(from + READ_WINDOW, limit) - 1);
      if (error) {
        console.error("getResultFeed failed", error.message);
        return from === 0 ? { entries: [], total: 0 } : { entries, total };
      }
      const page = (data ?? []) as unknown as ResultFeedEntry[];
      entries.push(...page);
      total = count ?? null;
      if (page.length < READ_WINDOW) break;
    }
    return { entries, total };
  }

  const { rows, error } = await readForSymbols<ResultFeedEntry>(symbols, limit, (_pushed, from, to) =>
    query(false).range(from, to),
  );
  if (error) console.error("getResultFeed failed", error);
  return { entries: rows, total: null };
}

/** Every filing of these companies for these quarters, on both bases. */
export async function getQuarterFilings(
  market: MarketCode,
  symbols: string[],
  periods: string[],
): Promise<QuarterFiling[]> {
  if (!symbols.length) return [];
  const supabase = await createClient();
  const read = (columns: string) =>
    supabase
      .from("quarterly_filings")
      .select(columns)
      .eq("market", market)
      .in("symbol", symbols)
      .in("period_end", periods)
      // Two bases for each quarter of each company, well inside one response.
      .limit(symbols.length * periods.length * 2);
  let { data, error } = await read(`${FILING_COLUMNS}, viewer_url`);
  if (error) {
    // A table without the readable link still has every figure; the card
    // links the machine-readable document instead.
    ({ data, error } = await read(FILING_COLUMNS));
  }
  if (error) {
    console.error("getQuarterFilings failed", error.message);
    return [];
  }
  return (data ?? []) as unknown as QuarterFiling[];
}

/** Company names from the latest run, for results stored without one. */
export async function getCompanyNames(
  market: MarketCode,
  symbols: string[],
): Promise<Map<string, string>> {
  if (!symbols.length) return new Map();
  const wanted = new Set(symbols);
  const names = await runCompanyNames(market);
  return new Map([...names].filter(([symbol]) => wanted.has(symbol)));
}

/**
 * The revenue, operating profit and net profit of every filing for these
 * quarters -- the three lines a growth rate here is worked out from, not the
 * whole `lines` document, since a whole quarter is some thousands of filings.
 * Narrowed to `symbols` when they fit in the request (`PUSH_DOWN_MAX`); a
 * larger scope is read whole and the caller keeps its own.
 *
 * The page cannot ask by symbol past that, since a thousand symbols do not
 * fit in a URL. Read in windows, the later ones together.
 */
export async function getQuarterLines(
  market: MarketCode,
  periods: string[],
  symbols: string[] | null = null,
): Promise<QuarterFiling[]> {
  if (symbols && symbols.length === 0) return [];
  const supabase = await createClient();
  const window = (from: number) => {
    let built = supabase
      .from("quarterly_filings")
      .select(
        "symbol, period_end, is_consolidated, revenue:lines->revenue, operating_profit:lines->operating_profit, net_profit:lines->net_profit",
        { count: "exact" },
      )
      .eq("market", market)
      .in("period_end", periods);
    if (symbols && symbols.length <= PUSH_DOWN_MAX) built = built.in("symbol", symbols);
    return built
      .order("symbol", { ascending: true })
      .order("period_end", { ascending: true })
      .order("is_consolidated", { ascending: true })
      .range(from, from + READ_WINDOW - 1);
  };
  type Row = Omit<QuarterFiling, "lines"> & {
    revenue: number | null;
    operating_profit: number | null;
    net_profit: number | null;
  };
  const toFiling = ({ revenue, operating_profit, net_profit, ...rest }: Row): QuarterFiling => ({
    ...rest,
    lines: { revenue, operating_profit, net_profit },
  });
  const first = await window(0);
  if (first.error) {
    console.error("getQuarterLines failed", first.error.message);
    return [];
  }
  const rows = ((first.data ?? []) as unknown as Row[]).map(toFiling);
  const rest = await Promise.all(
    Array.from({ length: Math.max(0, Math.ceil((first.count ?? 0) / READ_WINDOW) - 1) }, (_, index) =>
      window((index + 1) * READ_WINDOW),
    ),
  );
  for (const page of rest) {
    if (page.error) {
      // A short read would silently drop companies from the result: show none.
      console.error("getQuarterLines failed", page.error.message);
      return [];
    }
    rows.push(...((page.data ?? []) as unknown as Row[]).map(toFiling));
  }
  return rows;
}
