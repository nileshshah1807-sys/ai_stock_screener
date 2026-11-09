import "server-only";

import { monthsBefore } from "@/lib/financials.mjs";
import { monthlyMovers, profitMovers, pulseBases } from "@/lib/home-market.mjs";
import { decodeRow, indexPoints, metricPoints } from "@/lib/market-breadth.mjs";
import type { MarketCode } from "@/lib/markets";
import { getLatestRun } from "@/lib/queries";
import {
  getLatestResultQuarter,
  getQuarterLines,
  getResultFeed,
  type QuarterFiling,
} from "@/lib/results";
import { groupByAnnouncedDay, quarterEnds, resultCard } from "@/lib/results.mjs";
import { createClient } from "@/lib/supabase/server";

/** PostgREST returns at most this many rows per request. */
const WINDOW = 1000;
/** Headline indices on the pulse card: the Market page's first ones. */
const PULSE_INDICES = 4;
const MONTHLY_LIMIT = 5;
const SEASON_LIMIT = 3;
/** Enough for a peak day (about 900 companies report in a week). */
const SEASON_READ = 400;

export type PulseIndex = NonNullable<ReturnType<typeof pulseBases>> & { name: string };

/** The headline indices' closes, reduced to the bases the card's changes are measured from. */
export async function getPulseIndices(market: MarketCode): Promise<PulseIndex[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("market_breadth")
    .select("name, sessions, series")
    .eq("market", market)
    .eq("scope", "index")
    .order("position")
    .limit(PULSE_INDICES);
  if (error) {
    console.error("getPulseIndices failed", error.message);
    return [];
  }
  return (data ?? []).flatMap((row) => {
    const bases = pulseBases(indexPoints(decodeRow(row)));
    return bases ? [{ name: row.name as string, ...bases }] : [];
  });
}

/** Every row of a ranged read, a window at a time, until a short one. */
async function readAll<T>(read: (from: number, to: number) => PromiseLike<{ data: unknown; error: { message: string } | null }>) {
  const rows: T[] = [];
  for (let from = 0; ; from += WINDOW) {
    const { data, error } = await read(from, from + WINDOW - 1);
    if (error) throw new Error(error.message);
    const page = (data ?? []) as T[];
    rows.push(...page);
    if (page.length < WINDOW) return rows;
  }
}

export type MonthlyMover = { symbol: string; company: string | null; investment_rank: number | null; pct_change_1m: number };
export type MonthlyMovers = Record<string, { gainers: MonthlyMover[]; losers: MonthlyMover[] }>;

/**
 * One-month gainers and losers inside each of `indices`, from the run's
 * `pct_change_1m`. No rating is read, so the card needs no admin check.
 */
export async function getMonthlyMovers(market: MarketCode, indices: string[]): Promise<MonthlyMovers> {
  const run = await getLatestRun(market);
  if (!run || !indices.length) return {};
  // The result changes once an evening and is the same for every viewer (no
  // rating is read), so it is kept per server instance; a new run misses by key.
  const key = `${market}:${run.run_date}:${indices.join("|")}`;
  const hit = monthlyMemo.get(key);
  if (hit && Date.now() - hit.at < MONTHLY_MEMO_MS) return hit.value;
  const value = await readMonthlyMovers(market, indices, run.run_date);
  // An empty result may be a failed read: not kept, so it is retried.
  if (Object.keys(value).length) {
    if (monthlyMemo.size >= 20) monthlyMemo.clear();
    monthlyMemo.set(key, { at: Date.now(), value });
  }
  return value;
}

/** Symbols per `in` filter: about 8 KB of URL. */
const SYMBOL_CHUNK = 400;
const MONTHLY_MEMO_MS = 3_600_000;
const monthlyMemo = new Map<string, { at: number; value: MonthlyMovers }>();

async function readMonthlyMovers(market: MarketCode, indices: string[], runDate: string): Promise<MonthlyMovers> {
  const supabase = await createClient();
  try {
    const members = await readAll<{ index_name: string; symbol: string }>((from, to) =>
      supabase.from("index_members").select("index_name, symbol").eq("market", market).in("index_name", indices).order("symbol").range(from, to),
    );
    // Only the members' rows, in chunks that keep the URL short, rather than
    // paging through the whole run.
    const symbols = [...new Set(members.map((member) => member.symbol))];
    const stocks: MonthlyMover[] = [];
    for (let at = 0; at < symbols.length; at += SYMBOL_CHUNK) {
      stocks.push(
        ...(await readAll<MonthlyMover>((from, to) =>
          supabase
            .from("screener_snapshot_visible")
            .select("symbol, company, investment_rank, pct_change_1m")
            .eq("market", market)
            .eq("run_date", runDate)
            .in("symbol", symbols.slice(at, at + SYMBOL_CHUNK))
            .order("symbol")
            .range(from, to),
        )),
      );
    }
    const bySymbols = new Map<string, string[]>();
    for (const { index_name, symbol } of members) bySymbols.set(index_name, [...(bySymbols.get(index_name) ?? []), symbol]);
    return Object.fromEntries(monthlyMovers(bySymbols, stocks, MONTHLY_LIMIT)) as MonthlyMovers;
  } catch (error) {
    console.error("getMonthlyMovers failed", error instanceof Error ? error.message : error);
    return {};
  }
}

export type SeasonMover = { symbol: string; company: string | null; change: number };
export type ResultsSeason = {
  /** The market day the count is for: today, or the latest day with results. */
  day: string;
  count: number;
  rises: SeasonMover[];
  falls: SeasonMover[];
};

/**
 * Companies that reported on the latest day anyone did (today, once a result
 * is in) and the largest year-on-year net profit rises and falls among them,
 * by the Results page's own card rule. Null when no result is stored.
 */
export async function getResultsSeason(market: MarketCode, today: string, timeZone: string): Promise<ResultsSeason | null> {
  const offered = quarterEnds(today);
  const quarter = (await getLatestResultQuarter(market, offered)) ?? offered[0];
  const { entries } = await getResultFeed(market, { quarter, limit: SEASON_READ });
  const latest = groupByAnnouncedDay(entries, timeZone)[0];
  if (!latest?.date) return null;

  const lines = await getQuarterLines(
    market,
    [quarter, monthsBefore(quarter, 3), monthsBefore(quarter, 12)],
    latest.entries.map((entry) => entry.symbol),
  );
  const filingsOf = new Map<string, QuarterFiling[]>();
  for (const filing of lines) filingsOf.set(filing.symbol, [...(filingsOf.get(filing.symbol) ?? []), filing]);
  const cards = latest.entries.map((entry) => resultCard(entry, filingsOf.get(entry.symbol) ?? [], entry.period_end));
  return { day: latest.date, count: latest.entries.length, ...profitMovers(cards, SEASON_LIMIT) };
}

export type BreadthNow = { session: string; e50: number | null; e200: number | null };

/** The market's share of stocks above their 50- and 200-day averages at the last published close, in percent. */
export async function getBreadthNow(market: MarketCode): Promise<BreadthNow | null> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("market_breadth")
    .select("sessions, series")
    .eq("market", market)
    .eq("scope", "market")
    .eq("name", "")
    .maybeSingle();
  if (error) console.error("getBreadthNow failed", error.message);
  const decoded = decodeRow(data);
  if (!decoded) return null;
  const share = (key: string) => metricPoints(decoded, key, `${key}d`, "share").at(-1)?.value ?? null;
  return { session: decoded.dates.at(-1) as string, e50: share("e50"), e200: share("e200") };
}
