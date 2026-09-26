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
  pickOption,
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

/** Symbols per current-state request, to keep each URL well under its limit. */
const STATE_CHUNK = 150;

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

export type ClosedTrade = {
  symbol: string;
  company: string | null;
  logoDomain: string | null;
  boughtOn: string | null;
  boughtAt: number | null;
  soldOn: string;
  soldAt: number | null;
  returnPct: number | null;
  /** Bought from a backtest ranking rather than a published one. */
  backtest: boolean;
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
      /** Which list the basket picks from: "all", or a filtered pick. */
      pick: string;
      /** Set when a rating pick moved the start forward to the first rated ranking. */
      pickStartMovedFrom: string | null;
      /** Rounds where fewer than N stocks passed the pick. */
      shortRounds: number;
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
      /** Every position the basket has sold, oldest sale first. */
      closed: ClosedTrade[];
      benchmark: {
        name: string;
        returnPct: number | null;
        through: string | null;
        curve: { time: string; value: number }[];
      };
      universe: { returnPct: number | null; through: string | null; sessions: number };
    };

type Pick = ReturnType<typeof pickOption>;

/**
 * The top N of every ranking a portfolio is rebuilt from, within a pick.
 *
 * Backtest dates read `simulated_rankings`, where each pick's own rank is
 * stored, so a filtered top N is one range read like the plain one. Published
 * dates read `screener_history`: the whole ranking the same way, a filtered
 * pick as one small query per date -- there are only as many as there are
 * published rebalances in the window -- all sent at once.
 */
async function getRankingTops(
  supabase: Supabase,
  market: MarketCode,
  dates: string[],
  topN: number,
  liveFrom: string,
  pick: Pick,
): Promise<Map<string, HistoryRow[]>> {
  const tops = new Map<string, HistoryRow[]>(dates.map((date) => [date, []]));
  const collect = (table: string, data: unknown[] | null, error: { message: string } | null) => {
    if (error) {
      console.error(`getRankingTops(${table}) failed`, error.message);
      return;
    }
    for (const row of (data ?? []) as (HistoryRow & { observed_on: string })[]) {
      tops.get(row.observed_on)?.push(row);
    }
  };

  const backtestDates = dates.filter((date) => date < liveFrom);
  const liveDates = dates.filter((date) => date >= liveFrom);
  const column = pick.column ?? "investment_rank";

  const backtest = async () => {
    if (!backtestDates.length) return;
    const chunks = Math.max(1, Math.ceil((backtestDates.length * topN) / FETCH_CHUNK));
    const results = await Promise.all(
      Array.from({ length: chunks }, (_, index) =>
        supabase
          .from("simulated_rankings")
          .select("observed_on, symbol, investment_rank, rating, stage")
          .eq("market", market)
          .in("observed_on", backtestDates)
          .lte(column, topN)
          .order("observed_on")
          .order(column)
          .range(index * FETCH_CHUNK, (index + 1) * FETCH_CHUNK - 1),
      ),
    );
    for (const { data, error } of results) collect("simulated_rankings", data, error);
  };

  const live = async () => {
    if (!liveDates.length) return;
    const columns = "observed_on, symbol, company, investment_rank, rating, stage";
    if (!pick.column) {
      const chunks = Math.max(1, Math.ceil((liveDates.length * topN) / FETCH_CHUNK));
      const results = await Promise.all(
        Array.from({ length: chunks }, (_, index) =>
          supabase
            .from("screener_history")
            .select(columns)
            .eq("market", market)
            .in("observed_on", liveDates)
            .lte("investment_rank", topN)
            .order("observed_on")
            .order("investment_rank")
            .range(index * FETCH_CHUNK, (index + 1) * FETCH_CHUNK - 1),
        ),
      );
      for (const { data, error } of results) collect("screener_history", data, error);
      return;
    }
    const results = await Promise.all(
      liveDates.map((date) => {
        let query = supabase
          .from("screener_history")
          .select(columns)
          .eq("market", market)
          .eq("observed_on", date)
          .not("investment_rank", "is", null);
        if (pick.ratings) query = query.in("rating", pick.ratings);
        if (pick.stage) query = query.eq("stage", pick.stage);
        if (pick.maxAdvanceAge) query = query.lte("advance_age_days", pick.maxAdvanceAge);
        return query.order("investment_rank").limit(topN);
      }),
    );
    for (const { data, error } of results) collect("screener_history", data, error);
  };

  await Promise.all([backtest(), live()]);
  return tops;
}

/**
 * The first backtest ranking that carries ratings, or null when none does.
 * Backtest weeks before FY2023 filings have too little fundamental coverage to
 * rate, so a rating pick cannot start earlier than this.
 */
async function getFirstRatedBacktest(supabase: Supabase, market: MarketCode): Promise<string | null> {
  const { data, error } = await supabase
    .from("simulated_rankings")
    .select("observed_on")
    .eq("market", market)
    .not("rating", "is", null)
    .order("observed_on")
    .limit(1)
    .maybeSingle();
  if (error) {
    console.error("getFirstRatedBacktest failed", error.message);
    return null;
  }
  return (data?.observed_on as string | undefined) ?? null;
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
  // A long rebalanced window can name several hundred symbols, which would
  // not fit one request's URL; the chunks go out together.
  const chunks: string[][] = [];
  for (let index = 0; index < symbols.length; index += STATE_CHUNK) {
    chunks.push(symbols.slice(index, index + STATE_CHUNK));
  }
  const results = await Promise.all(
    chunks.map((part) =>
      fromSnapshot
        ? supabase
            .from("screener_snapshot")
            .select("symbol, company, investment_rank, rating, stage, logo_domain")
            .eq("market", market)
            .eq("run_date", asOf)
            .in("symbol", part)
        : supabase
            .from("screener_history")
            .select("symbol, company, investment_rank, rating, stage")
            .eq("market", market)
            .eq("observed_on", asOf)
            .in("symbol", part),
    ),
  );
  const state = new Map<string, HistoryRow>();
  for (const { data, error } of results) {
    if (error) console.error("getLatestState failed", error.message);
    for (const row of (data ?? []) as HistoryRow[]) state.set(row.symbol, row);
  }
  return state;
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
    pick: pickValue,
  }: { from: string | null; topN: number; costs: boolean; rebalance: string | null; pick: string | null },
): Promise<ReturnsReport> {
  const supabase = await createClient();
  const pick = pickOption(pickValue);
  const [liveDates, simulatedDates, calendar, benchmarkLevels, latestRun, firstRated] = await Promise.all([
    getRankingDates(market.code),
    getSimulatedDates(market.code),
    getPriceCalendar(market.code),
    getBenchmarkLevels(supabase, market),
    getLatestRun(market.code),
    pick.ratings ? getFirstRatedBacktest(supabase, market.code) : Promise.resolve(null),
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

  let rankDate = snapRankingDate(rankingDates, from)!;
  // A rating pick cannot start where no rating exists: before the first rated
  // backtest week (or, with none, before the live record) it moves forward
  // and says so, rather than holding cash for the years it cannot see.
  let pickStartMovedFrom: string | null = null;
  if (pick.ratings && rankDate < liveFrom) {
    const earliest = firstRated && firstRated < liveFrom ? firstRated : liveFrom;
    if (rankDate < earliest) {
      pickStartMovedFrom = rankDate;
      rankDate = rankingDates.find((date) => date >= earliest) ?? rankDate;
    }
  }
  const option = rebalanceOption(rebalance);
  const schedule = rebalanceDates(rankingDates, rankDate, option);
  const sessions = calendar ?? [];
  // The market calendar can lag the latest run by a rebuild; the ranking dates
  // cover those sessions, so the union is the complete list.
  const allSessions = [...new Set([...sessions, ...dates])].sort();
  const entrySession = entrySessionAfter(allSessions, rankDate) ?? asOf;

  const basketBranch = async () => {
    const tops = await getRankingTops(supabase, market.code, schedule, topN, liveFrom, pick);
    const rounds = schedule.map((date) => ({
      rankDate: date,
      entrySession: entrySessionAfter(allSessions, date) ?? asOf,
      symbols: (tops.get(date) ?? []).map((row) => row.symbol),
    }));
    const lastRound = rounds[rounds.length - 1];
    const symbols = [...new Set(rounds.flatMap((round) => round.symbols))];
    const [closes, now] = await Promise.all([
      getAdjustedCloses(supabase, market.code, symbols, rankDate, sessions),
      // Every symbol the basket ever held: current holdings, and the names on
      // closed positions, which need their company and logo too.
      getLatestState(supabase, market.code, asOf, latestRun?.run_date ?? null, symbols),
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
    pick: pick.value,
    pickStartMovedFrom,
    shortRounds: rounds.filter((round) => round.symbols.length < topN).length,
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
    closed: result.closedTrades.map((trade) => {
      const state = now.get(trade.symbol);
      const round = rounds.find((item) => item.entrySession === trade.boughtRound);
      return {
        symbol: trade.symbol,
        company: state?.company ?? null,
        logoDomain: state?.logo_domain ?? null,
        boughtOn: trade.entry?.time ?? null,
        boughtAt: trade.entry?.close ?? null,
        soldOn: trade.exit?.time ?? trade.soldOn,
        soldAt: trade.exit?.close ?? null,
        returnPct: trade.returnPct,
        backtest: round ? round.rankDate < liveFrom : false,
      };
    }),
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
