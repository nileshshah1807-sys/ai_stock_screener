import "server-only";

import { cache } from "react";

import { getLatestRun, getPriceCalendar } from "@/lib/queries";
import type { Market, MarketCode } from "@/lib/markets";
import { decodeRow, indexPoints } from "@/lib/market-breadth.mjs";
import {
  COST_PER_SIDE_PCT,
  decodeCloses,
  entrySessionAfter,
  equalWeightReturn,
  indexReturns,
  modelForDate,
  needsAdjustedPrice,
  portfolioReturns,
  rebalanceDates,
  rebalanceOption,
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
 * `expectedRows` -- the latest run's row count, which the layout has already
 * read -- sizes the chunks up front so they all go out at once, instead of a
 * first request that only asks how many there are. A day with more rows than
 * expected (the universe grew) is finished off one chunk at a time.
 */
async function readHistoryDay(
  supabase: Supabase,
  market: MarketCode,
  date: string,
  columns: string,
  expectedRows: number,
): Promise<HistoryRow[]> {
  const chunk = (offset: number) =>
    supabase
      .from("screener_history")
      .select(columns)
      .eq("market", market)
      .eq("observed_on", date)
      .order("symbol")
      .range(offset, offset + FETCH_CHUNK - 1);

  const chunks = Math.max(1, Math.ceil(expectedRows / FETCH_CHUNK));
  const results = await Promise.all(
    Array.from({ length: chunks }, (_, index) => chunk(index * FETCH_CHUNK)),
  );
  const rows: HistoryRow[] = [];
  let lastFull = false;
  for (const result of results) {
    if (result.error) {
      console.error("readHistoryDay failed", result.error.message);
      return rows;
    }
    const data = (result.data ?? []) as unknown as HistoryRow[];
    rows.push(...data);
    lastFull = data.length === FETCH_CHUNK;
  }
  for (let offset = chunks * FETCH_CHUNK; lastFull; offset += FETCH_CHUNK) {
    const result = await chunk(offset);
    if (result.error) {
      console.error("readHistoryDay failed", result.error.message);
      break;
    }
    const data = (result.data ?? []) as unknown as HistoryRow[];
    rows.push(...data);
    lastFull = data.length === FETCH_CHUNK;
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
 *
 * The base and the tail are read together. Every base is rebuilt in one pass
 * against the shared calendar, so the tail starts at the calendar's last
 * session without waiting to see each base; only symbols with no base at all
 * cost a second read. A base that ends before the calendar does belongs to a
 * stock that stopped trading, which has no later closes to miss.
 */
async function getAdjustedCloses(
  supabase: Supabase,
  market: MarketCode,
  symbols: string[],
  since: string,
  sessions: string[],
): Promise<Map<string, Point[]>> {
  const out = new Map<string, Point[]>();
  if (!symbols.length) return out;

  const chunks: string[][] = [];
  for (let index = 0; index < symbols.length; index += SERIES_CHUNK) {
    chunks.push(symbols.slice(index, index + SERIES_CHUNK));
  }
  const calendarEnd = sessions[sessions.length - 1] ?? since;
  const tails = new Map<string, Point[]>();
  const [seriesResults] = await Promise.all([
    Promise.all(
      chunks.map((part) =>
        supabase
          .from("price_series")
          // No volumes: this page never reads them, and they are a third of the row.
          .select("symbol, session_deltas, closes, last_session")
          .eq("market", market)
          .in("symbol", part),
      ),
    ),
    readTails(supabase, market, symbols, calendarEnd, tails),
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

  // A symbol with no adjusted base needs raw closes from the start of the
  // window, not just since the last rebuild.
  const unbased = symbols.filter((symbol) => !bases.has(symbol));
  if (unbased.length) {
    for (const symbol of unbased) tails.delete(symbol);
    await readTails(supabase, market, unbased, since, tails);
  }

  for (const symbol of symbols) {
    // withTail drops tail points the base already covers; the base is adjusted.
    out.set(symbol, withTail(bases.get(symbol)?.points ?? [], tails.get(symbol) ?? []));
  }
  return out;
}

/** Raw daily closes after `after` for each symbol, added to `into`. */
async function readTails(
  supabase: Supabase,
  market: MarketCode,
  symbols: string[],
  after: string,
  into: Map<string, Point[]>,
): Promise<void> {
  for (let offset = 0; ; offset += FETCH_CHUNK) {
    const { data, error } = await supabase
      .from("screener_history")
      .select("symbol, observed_on, current_price")
      .eq("market", market)
      .in("symbol", symbols)
      .gt("observed_on", after)
      .order("symbol")
      .order("observed_on")
      .range(offset, offset + FETCH_CHUNK - 1);
    if (error) {
      // A stale tail loses the last session or two; it must not blank the page.
      console.error("getAdjustedCloses tail failed", error.message);
      return;
    }
    for (const row of data ?? []) {
      const price = Number(row.current_price);
      if (!(price > 0)) continue;
      const symbol = row.symbol as string;
      if (!into.has(symbol)) into.set(symbol, []);
      into.get(symbol)!.push({ time: row.observed_on as string, close: price });
    }
    if (!data || data.length < FETCH_CHUNK) return;
  }
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
  expectedRows: number,
  sessions: string[],
): Promise<{ returnPct: number | null; counted: number; total: number }> {
  const [ranked, entryRows, lastRows] = await Promise.all([
    readHistoryDay(supabase, market, rankDate, "symbol, investment_rank", expectedRows),
    readHistoryDay(supabase, market, entryDay, "symbol, current_price", expectedRows),
    readHistoryDay(supabase, market, asOf, "symbol, current_price", expectedRows),
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
    sessions,
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
  logoDomain: string | null;
  /** Rank, rating and stage on the ranking the stock was last bought from. */
  rankThen: number | null;
  ratingThen: string | null;
  stageThen: string | null;
  /** The entry session of the round that first bought this holding. */
  heldSince: string | null;
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

export type RebalanceSummary = {
  option: string;
  /** Rebalances after the first purchase. */
  count: number;
  bought: number;
  sold: number;
  /** Costs paid across every round, as points of the portfolio. */
  costPct: number;
  lastRankDate: string;
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
      rebalance: RebalanceSummary;
      basket: {
        grossPct: number | null;
        netPct: number | null;
        /** Net of costs, and without: the page switches between them locally. */
        curve: { time: string; value: number }[];
        grossCurve: { time: string; value: number }[];
      };
      holdings: HoldingRow[];
      benchmark: {
        name: string;
        returnPct: number | null;
        through: string | null;
        curve: { time: string; value: number }[];
      };
      universe: { returnPct: number | null; counted: number; total: number };
    };

/**
 * The top N of every ranking a portfolio is rebuilt from, in one paged read
 * rather than a request per rebalance.
 */
async function getRankingTops(
  supabase: Supabase,
  market: MarketCode,
  dates: string[],
  topN: number,
): Promise<Map<string, HistoryRow[]>> {
  const tops = new Map<string, HistoryRow[]>(dates.map((date) => [date, []]));
  for (let offset = 0; ; offset += FETCH_CHUNK) {
    const { data, error } = await supabase
      .from("screener_history")
      .select("observed_on, symbol, company, investment_rank, rating, stage")
      .eq("market", market)
      .in("observed_on", dates)
      .lte("investment_rank", topN)
      .order("observed_on")
      .order("investment_rank")
      .range(offset, offset + FETCH_CHUNK - 1);
    if (error) {
      console.error("getRankingTops failed", error.message);
      return tops;
    }
    for (const row of data ?? []) {
      tops.get(row.observed_on as string)?.push(row as HistoryRow);
    }
    if (!data || data.length < FETCH_CHUNK) return tops;
  }
}

/** Rank, rating, stage and logo for the current holdings, from the latest run. */
async function getLatestState(
  supabase: Supabase,
  market: MarketCode,
  asOf: string,
  latestRunDate: string | null,
  symbols: string[],
): Promise<Map<string, HistoryRow & { logo_domain?: string | null }>> {
  if (!symbols.length) return new Map();
  // The snapshot carries the logo domain; history does not. They describe the
  // same run whenever the latest run is the latest ranking, which is always
  // true outside the minutes a publish is in flight.
  const fromSnapshot = latestRunDate === asOf;
  const { data, error } = fromSnapshot
    ? await supabase
        .from("screener_snapshot")
        .select("symbol, investment_rank, rating, stage, logo_domain")
        .eq("market", market)
        .eq("run_date", asOf)
        .in("symbol", symbols)
    : await supabase
        .from("screener_history")
        .select("symbol, investment_rank, rating, stage")
        .eq("market", market)
        .eq("observed_on", asOf)
        .in("symbol", symbols);
  if (error) console.error("getLatestState failed", error.message);
  return new Map(((data ?? []) as HistoryRow[]).map((row) => [row.symbol, row]));
}

/**
 * Two waves of reads after the ranking dates, instead of five: the basket's
 * rankings, prices and current state on one branch, and the universe
 * comparison -- which needs only the start date -- on the other, in parallel.
 * Costs are computed both ways every time, so toggling them needs no request.
 */
export async function getReturnsReport(
  market: Market,
  {
    from,
    topN,
    costs,
    rebalance,
  }: { from: string | null; topN: number; costs: boolean; rebalance: string | null },
): Promise<ReturnsReport> {
  const supabase = await createClient();
  const [dates, calendar, benchmarkLevels, latestRun] = await Promise.all([
    getRankingDates(market.code),
    getPriceCalendar(market.code),
    getBenchmarkLevels(supabase, market),
    getLatestRun(market.code),
  ]);
  if (!dates.length) return { status: "no-history" };
  const asOf = dates[dates.length - 1];
  // The latest ranking has no session after it yet, so nothing it lists has
  // been buyable. It stays out of the picker rather than showing a 0% return.
  const rankingDates = dates.slice(0, -1);
  if (!rankingDates.length) return { status: "too-early", asOf };

  const rankDate = snapRankingDate(rankingDates, from)!;
  const option = rebalanceOption(rebalance);
  const schedule = rebalanceDates(rankingDates, rankDate, option);
  const sessions = calendar ?? [];
  // The market calendar can lag the latest run by a rebuild; the ranking dates
  // cover those sessions, so the union is the complete list.
  const allSessions = [...new Set([...sessions, ...dates])].sort();
  const entrySession = entrySessionAfter(allSessions, rankDate) ?? asOf;
  // The universe is priced from history, which has a row only on run days:
  // the first ranking after the start, known without any further read.
  const entryDay = dates.find((date) => date > rankDate) ?? asOf;
  // Headroom over the latest count, so a slightly larger past universe still
  // arrives in the first wave.
  const expectedRows = Math.ceil((latestRun?.row_count ?? FETCH_CHUNK) * 1.1);

  const basketBranch = async () => {
    const tops = await getRankingTops(supabase, market.code, schedule, topN);
    const rounds = schedule.map((date) => ({
      rankDate: date,
      entrySession: entrySessionAfter(allSessions, date) ?? asOf,
      symbols: (tops.get(date) ?? []).map((row) => row.symbol),
    }));
    const lastRound = rounds[rounds.length - 1];
    const symbols = [...new Set(rounds.flatMap((round) => round.symbols))];
    const [closes, now] = await Promise.all([
      getAdjustedCloses(supabase, market.code, symbols, rankDate, sessions),
      getLatestState(supabase, market.code, asOf, latestRun?.run_date ?? null, lastRound.symbols),
    ]);
    return { tops, rounds, lastRound, closes, now };
  };

  const [{ tops, rounds, lastRound, closes, now }, universe] = await Promise.all([
    basketBranch(),
    getUniverseReturn(supabase, market.code, rankDate, entryDay, asOf, expectedRows, sessions),
  ]);

  const result = portfolioReturns(rounds, closes, { asOf, costPerSidePct: COST_PER_SIDE_PCT });
  const lastRows = tops.get(lastRound.rankDate) ?? [];

  const holdings: HoldingRow[] = lastRows.map((row, index) => {
    const stock = result.stocks[index];
    const latest = now.get(row.symbol);
    return {
      symbol: row.symbol,
      company: row.company ?? null,
      logoDomain: latest?.logo_domain ?? null,
      rankThen: row.investment_rank ?? null,
      ratingThen: row.rating ?? null,
      stageThen: row.stage ?? null,
      heldSince: stock?.heldSince ?? null,
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

  const later = result.trades.slice(1);
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
    rebalance: {
      option: option.value,
      count: later.length,
      bought: later.reduce((sum, trade) => sum + trade.bought.length, 0),
      sold: later.reduce((sum, trade) => sum + trade.sold.length, 0),
      costPct: result.trades.reduce((sum, trade) => sum + trade.costPct, 0),
      lastRankDate: lastRound.rankDate,
    },
    basket: {
      grossPct: result.grossPct,
      netPct: result.netPct,
      curve: result.curve,
      grossCurve: result.grossCurve,
    },
    holdings,
    benchmark: { name: market.benchmark, ...benchmark },
    universe,
  };
}
