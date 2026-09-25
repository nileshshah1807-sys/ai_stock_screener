import "server-only";

import { cache } from "react";

import { getPriceCalendar } from "@/lib/queries";
import type { Market, MarketCode } from "@/lib/markets";
import { decodeRow, indexPoints } from "@/lib/market-breadth.mjs";
import {
  basketReturns,
  COST_PER_SIDE_PCT,
  decodeCloses,
  entrySessionAfter,
  equalWeightReturn,
  indexReturns,
  modelForDate,
  needsAdjustedPrice,
  snapRankingDate,
} from "@/lib/returns.mjs";
import { withTail } from "@/lib/price-series.mjs";
import { createClient } from "@/lib/supabase/server";

/**
 * Reads for the Returns page: a past ranking's top N, priced forward to the
 * latest run.
 *
 * Separate from `lib/queries.ts` because every read here serves one
 * calculation and only makes sense in its order -- the ranking picks the
 * symbols, the symbols pick the price series, the entry session picks the
 * universe day. The arithmetic itself is in `returns.mjs`, where it is tested.
 *
 * Nothing here writes, and nothing needs a new table: rankings and daily
 * closes come from `screener_history`, adjusted history from `price_series`,
 * index levels from `market_breadth`.
 */

type Supabase = Awaited<ReturnType<typeof createClient>>;
type Point = { time: string; close: number };

/** PostgREST caps a single response; anything universe-wide must be paged. */
const FETCH_CHUNK = 1000;

/**
 * At most this many universe members are re-read from the adjusted series.
 * Measured on NSE: ~100 over six weeks (splits, bonuses, and names that left
 * the universe). The cap only bounds a pathological day; members past it are
 * left out of the equal-weight figure and counted as such.
 */
const MAX_ADJUSTED_REREADS = 250;

/** Symbols per `price_series` request, so no single response is several MB. */
const SERIES_CHUNK = 50;

type HistoryRow = {
  symbol: string;
  company?: string | null;
  investment_rank?: number | null;
  rating?: string | null;
  stage?: string | null;
  current_price?: number | null;
};

/**
 * Every date with a published ranking, ascending.
 *
 * Rank 1 exists exactly once per published run, so filtering on it turns a
 * universe-per-day table into one row per day without a DISTINCT, which
 * PostgREST cannot express.
 */
export const getRankingDates = cache(async (market: MarketCode): Promise<string[]> => {
  const supabase = await createClient();
  const dates: string[] = [];
  for (let offset = 0; ; offset += FETCH_CHUNK) {
    const { data, error } = await supabase
      .from("screener_history")
      .select("observed_on")
      .eq("market", market)
      .eq("investment_rank", 1)
      .order("observed_on", { ascending: true })
      .range(offset, offset + FETCH_CHUNK - 1);
    if (error) {
      console.error("getRankingDates failed", error.message);
      return dates;
    }
    for (const row of data ?? []) dates.push(row.observed_on as string);
    if (!data || data.length < FETCH_CHUNK) return dates;
  }
});

/**
 * One day of `screener_history`, every row, in symbol order.
 *
 * The first chunk asks for the exact count, and the remaining chunks then go
 * out together rather than one after another.
 */
async function readHistoryDay(
  supabase: Supabase,
  market: MarketCode,
  date: string,
  columns: string,
): Promise<HistoryRow[]> {
  const chunk = (offset: number, count = false) =>
    supabase
      .from("screener_history")
      .select(columns, count ? { count: "exact" } : undefined)
      .eq("market", market)
      .eq("observed_on", date)
      .order("symbol")
      .range(offset, offset + FETCH_CHUNK - 1);

  const first = await chunk(0, true);
  if (first.error) {
    console.error("readHistoryDay failed", first.error.message);
    return [];
  }
  const rows = [...((first.data ?? []) as unknown as HistoryRow[])];
  const total = first.count ?? rows.length;
  const offsets: number[] = [];
  for (let offset = FETCH_CHUNK; offset < total; offset += FETCH_CHUNK) offsets.push(offset);
  const rest = await Promise.all(offsets.map((offset) => chunk(offset)));
  for (const result of rest) {
    if (result.error) {
      console.error("readHistoryDay failed", result.error.message);
      continue;
    }
    rows.push(...((result.data ?? []) as unknown as HistoryRow[]));
  }
  return rows;
}

/**
 * Split-adjusted daily closes for a set of symbols, through the latest run.
 *
 * The same composition the stock chart uses: the back-adjusted `price_series`
 * base, then `screener_history`'s raw closes for the sessions since the base
 * was last rebuilt. A symbol with no base at all -- a new listing the
 * publisher has not reached -- falls back to raw closes from `since`.
 */
async function getAdjustedCloses(
  supabase: Supabase,
  market: MarketCode,
  symbols: string[],
  since: string,
): Promise<Map<string, Point[]>> {
  const out = new Map<string, Point[]>();
  if (!symbols.length) return out;

  const chunks: string[][] = [];
  for (let index = 0; index < symbols.length; index += SERIES_CHUNK) {
    chunks.push(symbols.slice(index, index + SERIES_CHUNK));
  }
  const [sessions, ...seriesResults] = await Promise.all([
    getPriceCalendar(market),
    ...chunks.map((part) =>
      supabase
        .from("price_series")
        // No volumes: this page never reads them, and they are a third of the row.
        .select("symbol, session_deltas, closes, last_session")
        .eq("market", market)
        .in("symbol", part),
    ),
  ]);

  const bases = new Map<string, { points: Point[]; last: string }>();
  for (const result of seriesResults) {
    if (result.error) {
      console.error("getAdjustedCloses failed", result.error.message);
      continue;
    }
    for (const row of result.data ?? []) {
      bases.set(row.symbol as string, {
        points: decodeCloses(row as { session_deltas: string; closes: string }, sessions ?? []),
        last: row.last_session as string,
      });
    }
  }

  // One tail read for every symbol, from the earliest point any of them needs.
  let tailFrom = since;
  if (symbols.every((symbol) => bases.has(symbol))) {
    tailFrom = [...bases.values()].map((base) => base.last).sort()[0] ?? since;
  }
  const tails = new Map<string, Point[]>();
  for (let offset = 0; ; offset += FETCH_CHUNK) {
    const { data, error } = await supabase
      .from("screener_history")
      .select("symbol, observed_on, current_price")
      .eq("market", market)
      .in("symbol", symbols)
      .gt("observed_on", tailFrom)
      .order("symbol")
      .order("observed_on")
      .range(offset, offset + FETCH_CHUNK - 1);
    if (error) {
      // A stale tail loses the last session or two; it must not blank the page.
      console.error("getAdjustedCloses tail failed", error.message);
      break;
    }
    for (const row of data ?? []) {
      const price = Number(row.current_price);
      if (!(price > 0)) continue;
      const symbol = row.symbol as string;
      if (!tails.has(symbol)) tails.set(symbol, []);
      tails.get(symbol)!.push({ time: row.observed_on as string, close: price });
    }
    if (!data || data.length < FETCH_CHUNK) break;
  }

  for (const symbol of symbols) {
    // withTail drops tail points the base already covers; the base is adjusted.
    out.set(symbol, withTail(bases.get(symbol)?.points ?? [], tails.get(symbol) ?? []));
  }
  return out;
}

/** The market's benchmark index levels, from the Market page's own rows. */
async function getBenchmarkLevels(
  supabase: Supabase,
  market: Market,
): Promise<{ time: string; value: number }[]> {
  const { data, error } = await supabase
    .from("market_breadth")
    .select("sessions, series")
    .eq("market", market.code)
    .eq("scope", "index")
    .eq("name", market.benchmark)
    .maybeSingle();
  if (error) {
    console.error("getBenchmarkLevels failed", error.message);
    return [];
  }
  return indexPoints(decodeRow(data as { sessions: string; series: string } | null));
}

/**
 * Equal-weight return of every stock the ranking scored, over the same window.
 *
 * The comparison the research uses: did picking the top N beat simply owning
 * everything the model ranked that day? Priced from two days of raw closes,
 * with the members whose pair looks like a corporate action, or who have no
 * price on one of the two days, re-read from the adjusted series.
 */
async function getUniverseReturn(
  supabase: Supabase,
  market: MarketCode,
  rankDate: string,
  entryDay: string,
  asOf: string,
): Promise<{ returnPct: number | null; counted: number; total: number }> {
  const [ranked, entryRows, lastRows] = await Promise.all([
    readHistoryDay(supabase, market, rankDate, "symbol, investment_rank"),
    readHistoryDay(supabase, market, entryDay, "symbol, current_price"),
    readHistoryDay(supabase, market, asOf, "symbol, current_price"),
  ]);
  const members = ranked
    .filter((row) => row.investment_rank !== null && row.investment_rank !== undefined)
    .map((row) => row.symbol);
  const entryPrice = new Map(entryRows.map((row) => [row.symbol, Number(row.current_price)]));
  const lastPrice = new Map(lastRows.map((row) => [row.symbol, Number(row.current_price)]));

  const pairs: { entry: number; last: number }[] = [];
  const reread: string[] = [];
  for (const symbol of members) {
    const entry = entryPrice.get(symbol);
    const last = lastPrice.get(symbol);
    if (needsAdjustedPrice(entry, last)) reread.push(symbol);
    else pairs.push({ entry: entry!, last: last! });
  }

  const adjusted = await getAdjustedCloses(
    supabase,
    market,
    reread.slice(0, MAX_ADJUSTED_REREADS),
    rankDate,
  );
  for (const points of adjusted.values()) {
    const window = points.filter((point) => point.time >= entryDay && point.time <= asOf);
    if (window.length) pairs.push({ entry: window[0].close, last: window[window.length - 1].close });
  }

  return { returnPct: equalWeightReturn(pairs), counted: pairs.length, total: members.length };
}

export type HoldingRow = {
  symbol: string;
  company: string | null;
  rankThen: number | null;
  ratingThen: string | null;
  stageThen: string | null;
  entry: Point | null;
  last: Point | null;
  delayedEntry: boolean;
  returnPct: number | null;
  /** Null when the symbol is not in the latest run at all. */
  rankNow: number | null;
  ratingNow: string | null;
  stageNow: string | null;
  inLatestRun: boolean;
};

export type ReturnsReport =
  | { status: "no-history" }
  | { status: "too-early"; asOf: string }
  | {
      status: "ok";
      /** Rankings that can be bought and held: every one before `asOf`. */
      rankingDates: string[];
      rankDate: string;
      entrySession: string;
      asOf: string;
      model: string | null;
      topN: number;
      costs: boolean;
      basket: { grossPct: number | null; netPct: number | null; curve: { time: string; value: number }[] };
      holdings: HoldingRow[];
      benchmark: {
        name: string;
        returnPct: number | null;
        through: string | null;
        curve: { time: string; value: number }[];
      };
      universe: { returnPct: number | null; counted: number; total: number };
    };

export async function getReturnsReport(
  market: Market,
  { from, topN, costs }: { from: string | null; topN: number; costs: boolean },
): Promise<ReturnsReport> {
  const dates = await getRankingDates(market.code);
  if (!dates.length) return { status: "no-history" };
  const asOf = dates[dates.length - 1];
  // The latest ranking has no session after it yet, so nothing it lists has
  // been buyable. It stays out of the picker rather than showing a 0% return.
  const rankingDates = dates.slice(0, -1);
  if (!rankingDates.length) return { status: "too-early", asOf };

  const rankDate = snapRankingDate(rankingDates, from)!;
  const supabase = await createClient();

  const [sessions, basketRows, benchmarkLevels] = await Promise.all([
    getPriceCalendar(market.code),
    supabase
      .from("screener_history")
      .select("symbol, company, investment_rank, rating, stage")
      .eq("market", market.code)
      .eq("observed_on", rankDate)
      .lte("investment_rank", topN)
      .order("investment_rank"),
    getBenchmarkLevels(supabase, market),
  ]);

  if (basketRows.error) console.error("getReturnsReport basket failed", basketRows.error.message);
  const basket = (basketRows.data ?? []) as HistoryRow[];
  const symbols = basket.map((row) => row.symbol);

  // The market calendar can lag the latest run by a rebuild; the ranking dates
  // cover those sessions, so the union is the complete list.
  const allSessions = [...new Set([...(sessions ?? []), ...dates])].sort();
  const entrySession = entrySessionAfter(allSessions, rankDate) ?? asOf;
  // The universe is priced from history, which has a row only on run days.
  const entryDay = dates.find((date) => date >= entrySession) ?? asOf;

  const [closes, nowResult, universe] = await Promise.all([
    getAdjustedCloses(supabase, market.code, symbols, rankDate),
    symbols.length
      ? supabase
          .from("screener_history")
          .select("symbol, investment_rank, rating, stage")
          .eq("market", market.code)
          .eq("observed_on", asOf)
          .in("symbol", symbols)
      : Promise.resolve({ data: [], error: null }),
    getUniverseReturn(supabase, market.code, rankDate, entryDay, asOf),
  ]);
  if (nowResult.error) console.error("getReturnsReport latest failed", nowResult.error.message);
  const now = new Map(((nowResult.data ?? []) as HistoryRow[]).map((row) => [row.symbol, row]));

  const result = basketReturns(
    symbols.map((symbol) => ({ symbol, points: closes.get(symbol) ?? [] })),
    { entrySession, asOf, costPerSidePct: costs ? COST_PER_SIDE_PCT : 0 },
  );

  const holdings: HoldingRow[] = basket.map((row, index) => {
    const stock = result.stocks[index];
    const latest = now.get(row.symbol);
    return {
      symbol: row.symbol,
      company: row.company ?? null,
      rankThen: row.investment_rank ?? null,
      ratingThen: row.rating ?? null,
      stageThen: row.stage ?? null,
      entry: stock?.entry ?? null,
      last: stock?.last ?? null,
      delayedEntry: stock?.delayedEntry ?? false,
      returnPct: stock?.returnPct ?? null,
      rankNow: latest?.investment_rank ?? null,
      ratingNow: latest?.rating ?? null,
      stageNow: latest?.stage ?? null,
      inLatestRun: Boolean(latest),
    };
  });

  const benchmark = indexReturns(benchmarkLevels, { entrySession, asOf });

  return {
    status: "ok",
    rankingDates,
    rankDate,
    entrySession,
    asOf,
    model: modelForDate(market.code, rankDate),
    topN,
    costs,
    basket: { grossPct: result.grossPct, netPct: result.netPct, curve: result.curve },
    holdings,
    benchmark: { name: market.benchmark, ...benchmark },
    universe,
  };
}
