import "server-only";

import { cache } from "react";

import { getLatestRun, getPriceCalendar } from "@/lib/queries";
import type { Market, MarketCode } from "@/lib/markets";
import { decodeRow, indexPoints } from "@/lib/market-breadth.mjs";
import {
  COST_PER_SIDE_PCT,
  compoundIndex,
  decodeCloses,
  entrySessionAfter,
  indexReturns,
  modelForDate,
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
 * symbols, the symbols pick the price series. The arithmetic itself is in
 * `returns.mjs`, where it is tested.
 *
 * Rankings come from two tables that must never be confused. Published ones
 * are in `screener_history`, from the first live run on. Before that the page
 * reaches back with `simulated_rankings`, which the point-in-time backtest
 * reconstructed with today's weights over the period they were fitted on, and
 * every figure built on one is labelled as backtest. Prices come from
 * `price_series`, index levels from `market_breadth`, and the equal-weight
 * universe from `universe_index`.
 */

type Supabase = Awaited<ReturnType<typeof createClient>>;
type Point = { time: string; close: number };

/** PostgREST caps a single response; anything longer must be paged. */
const FETCH_CHUNK = 1000;

/** Symbols per `price_series` request, so no single response is several MB. */
const SERIES_CHUNK = 50;

type HistoryRow = {
  symbol: string;
  company?: string | null;
  investment_rank?: number | null;
  rating?: string | null;
  stage?: string | null;
  logo_domain?: string | null;
};

/**
 * Every date with a ranking in `table`, ascending.
 *
 * Rank 1 exists exactly once per ranking, so filtering on it turns a
 * universe-per-day table into one row per day without a DISTINCT, which
 * PostgREST cannot express.
 */
async function rankingDatesIn(
  table: "screener_history" | "simulated_rankings",
  market: MarketCode,
): Promise<string[]> {
  const supabase = await createClient();
  const dates: string[] = [];
  for (let offset = 0; ; offset += FETCH_CHUNK) {
    const { data, error } = await supabase
      .from(table)
      .select("observed_on")
      .eq("market", market)
      .eq("investment_rank", 1)
      .order("observed_on", { ascending: true })
      .range(offset, offset + FETCH_CHUNK - 1);
    if (error) {
      // simulated_rankings is an optional migration; its absence only means
      // the page starts at the live record.
      console.error(`rankingDatesIn(${table}) failed`, error.message);
      return dates;
    }
    for (const row of data ?? []) dates.push(row.observed_on as string);
    if (!data || data.length < FETCH_CHUNK) return dates;
  }
}

/** Dates the dashboard actually published a ranking on. */
export const getRankingDates = cache((market: MarketCode) => rankingDatesIn("screener_history", market));

/** Dates the backtest reconstructed a ranking for. */
const getSimulatedDates = cache((market: MarketCode) => rankingDatesIn("simulated_rankings", market));

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
 * The daily equal-weight universe index over a window, compounded.
 *
 * One narrow read -- a row per session -- instead of pricing ~2,400 stocks on
 * two days, and it covers backtest-era windows, where no published history
 * exists to price them from. Before `storage/returns_backfill_schema.sql` is
 * applied the read fails and the comparison reads as unavailable.
 */
async function getUniverseIndex(
  supabase: Supabase,
  market: MarketCode,
  entrySession: string,
  asOf: string,
): Promise<{ returnPct: number | null; through: string | null; sessions: number }> {
  const rows: { observed_on: string; ew_return_pct: number }[] = [];
  for (let offset = 0; ; offset += FETCH_CHUNK) {
    const { data, error } = await supabase
      .from("universe_index")
      .select("observed_on, ew_return_pct")
      .eq("market", market)
      .gt("observed_on", entrySession)
      .lte("observed_on", asOf)
      .order("observed_on")
      .range(offset, offset + FETCH_CHUNK - 1);
    if (error) {
      console.error("getUniverseIndex failed", error.message);
      break;
    }
    rows.push(...((data ?? []) as { observed_on: string; ew_return_pct: number }[]));
    if (!data || data.length < FETCH_CHUNK) break;
  }
  return compoundIndex(rows, { entrySession, asOf });
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

export type TradeRound = {
  /** The ranking this round bought from. */
  rankDate: string;
  /** True when that ranking is a backtest, not a published one. */
  backtest: boolean;
  entrySession: string;
  periodEnd: string;
  bought: string[];
  sold: string[];
  costPct: number;
  /** What the basket did from this round to the next, before the round's cost. */
  returnPct: number | null;
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
      /** The first published ranking; every earlier one is a backtest. */
      liveFrom: string;
      /** Rounds, of all rounds bought, that used a backtest ranking. */
      backtestRounds: number;
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
      /** Every round, oldest first: the initial purchase, then each rebalance. */
      trades: TradeRound[];
      benchmark: {
        name: string;
        returnPct: number | null;
        through: string | null;
        curve: { time: string; value: number }[];
      };
      universe: { returnPct: number | null; through: string | null; sessions: number };
    };

/**
 * The top N of every ranking a portfolio is rebuilt from.
 *
 * Dates before the live record are read from `simulated_rankings`, the rest
 * from `screener_history`, in parallel. Each table is paged in one wave: the
 * row count is at most dates x N, so every chunk goes out at once.
 */
async function getRankingTops(
  supabase: Supabase,
  market: MarketCode,
  dates: string[],
  topN: number,
  liveFrom: string,
): Promise<Map<string, HistoryRow[]>> {
  const tops = new Map<string, HistoryRow[]>(dates.map((date) => [date, []]));
  const read = async (
    table: "screener_history" | "simulated_rankings",
    wanted: string[],
    columns: string,
  ) => {
    if (!wanted.length) return;
    const chunks = Math.max(1, Math.ceil((wanted.length * topN) / FETCH_CHUNK));
    const results = await Promise.all(
      Array.from({ length: chunks }, (_, index) =>
        supabase
          .from(table)
          .select(columns)
          .eq("market", market)
          .in("observed_on", wanted)
          .lte("investment_rank", topN)
          .order("observed_on")
          .order("investment_rank")
          .range(index * FETCH_CHUNK, (index + 1) * FETCH_CHUNK - 1),
      ),
    );
    for (const result of results) {
      if (result.error) {
        console.error(`getRankingTops(${table}) failed`, result.error.message);
        continue;
      }
      for (const row of (result.data ?? []) as unknown as (HistoryRow & { observed_on: string })[]) {
        tops.get(row.observed_on)?.push(row);
      }
    }
  };
  await Promise.all([
    read(
      "simulated_rankings",
      dates.filter((date) => date < liveFrom),
      "observed_on, symbol, investment_rank, stage",
    ),
    read(
      "screener_history",
      dates.filter((date) => date >= liveFrom),
      "observed_on, symbol, company, investment_rank, rating, stage",
    ),
  ]);
  return tops;
}

/** Rank, rating, stage, company and logo for the current holdings. */
async function getLatestState(
  supabase: Supabase,
  market: MarketCode,
  asOf: string,
  latestRunDate: string | null,
  symbols: string[],
): Promise<Map<string, HistoryRow>> {
  if (!symbols.length) return new Map();
  // The snapshot carries the logo domain; history does not. They describe the
  // same run whenever the latest run is the latest ranking, which is always
  // true outside the minutes a publish is in flight.
  const fromSnapshot = latestRunDate === asOf;
  const { data, error } = fromSnapshot
    ? await supabase
        .from("screener_snapshot")
        .select("symbol, company, investment_rank, rating, stage, logo_domain")
        .eq("market", market)
        .eq("run_date", asOf)
        .in("symbol", symbols)
    : await supabase
        .from("screener_history")
        .select("symbol, company, investment_rank, rating, stage")
        .eq("market", market)
        .eq("observed_on", asOf)
        .in("symbol", symbols);
  if (error) console.error("getLatestState failed", error.message);
  return new Map(((data ?? []) as HistoryRow[]).map((row) => [row.symbol, row]));
}

/**
 * Two waves of reads: the ranking dates, calendar, benchmark and run
 * metadata, then the basket branch (its rankings, prices and current state)
 * beside the universe index. Costs are computed both ways every time, so
 * toggling them needs no request.
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
  const [liveDates, simulatedDates, calendar, benchmarkLevels, latestRun] = await Promise.all([
    getRankingDates(market.code),
    getSimulatedDates(market.code),
    getPriceCalendar(market.code),
    getBenchmarkLevels(supabase, market),
    getLatestRun(market.code),
  ]);
  if (!liveDates.length) return { status: "no-history" };
  const liveFrom = liveDates[0];
  // A backtest ranking is used only where no published one exists.
  const dates = [...simulatedDates.filter((date) => date < liveFrom), ...liveDates];
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

  const basketBranch = async () => {
    const tops = await getRankingTops(supabase, market.code, schedule, topN, liveFrom);
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
    getUniverseIndex(supabase, market.code, entrySession, asOf),
  ]);

  const result = portfolioReturns(rounds, closes, { asOf, costPerSidePct: COST_PER_SIDE_PCT });
  const lastRows = tops.get(lastRound.rankDate) ?? [];

  const holdings: HoldingRow[] = lastRows.map((row, index) => {
    const stock = result.stocks[index];
    const latest = now.get(row.symbol);
    return {
      symbol: row.symbol,
      // Backtest rankings carry no company name; today's run supplies it.
      company: row.company ?? latest?.company ?? null,
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
    liveFrom,
    backtestRounds: rounds.filter((round) => round.rankDate < liveFrom).length,
    model: modelForDate(market.code, rankDate, rankDate < liveFrom),
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
    trades: result.trades.map((trade) => ({
      rankDate: trade.rankDate as string,
      backtest: (trade.rankDate as string) < liveFrom,
      entrySession: trade.entrySession,
      periodEnd: trade.periodEnd,
      bought: trade.bought,
      sold: trade.sold,
      costPct: trade.costPct,
      returnPct: trade.returnPct,
    })),
    benchmark: { name: market.benchmark, ...benchmark },
    universe,
  };
}
