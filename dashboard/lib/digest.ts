import "server-only";

import { readConcalls } from "@/lib/concalls";
import { digestFrom } from "@/lib/digest.mjs";
import { monthsBefore } from "@/lib/financials.mjs";
import { homeCached } from "@/lib/home-cache";
import { addDays } from "@/lib/home";
import { readAll } from "@/lib/home-market";
import type { Market } from "@/lib/markets";
import { getLatestResultQuarter, getResultFeed, readQuarterFilings, type Reader } from "@/lib/results";
import { quarterEnds } from "@/lib/results.mjs";
import { readUpcomingRows } from "@/lib/upcoming";

/** Newest results and calls the digest lists; a routine picks one to three. */
const DIGEST_ITEMS = 30;
/** Results due within the next five sessions, as calendar days. */
const UPCOMING_DAYS = 7;

/** The day's digest (lib/digest.mjs), shared for ten minutes; undefined without the service key. */
export function getDigest(market: Market, today: string) {
  return homeCached("digest", market.code, 600, (db) => readDigest(market, today, db), [today]);
}

/** Every read through the service-role client it is handed, so the cache never keeps a failure. */
async function readDigest(market: Market, today: string, db: Reader) {
  const offered = quarterEnds(today);
  const [quarter, calls, breadthRow, snapshot, upcoming] = await Promise.all([
    getLatestResultQuarter(market.code, offered, db),
    readConcalls(market.code, { limit: DIGEST_ITEMS }, db),
    readBreadthRow(market, db),
    readSnapshot(market, db),
    readUpcomingRows(market.code, "results", today, db),
  ]);
  const feed = quarter ? (await getResultFeed(market.code, { quarter, limit: DIGEST_ITEMS }, db)).entries : [];
  const filings = quarter
    ? await readQuarterFilings(
        market.code,
        feed.map((entry) => entry.symbol),
        [quarter, monthsBefore(quarter, 3), monthsBefore(quarter, 12)],
        db,
      )
    : [];
  return digestFrom({
    market: market.code,
    slug: market.slug,
    today,
    through: addDays(today, UPCOMING_DAYS),
    feed,
    filings: feed.length ? filings : [],
    calls,
    breadthRow,
    snapshot,
    upcoming: upcoming ?? [],
  });
}

async function readBreadthRow(market: Market, db: Reader) {
  const { data, error } = await db
    .from("market_breadth")
    .select("sessions, series")
    .eq("market", market.code)
    .eq("scope", "market")
    .eq("name", "")
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

/** The latest run's names, stages and one-day moves: no rating or score column. */
async function readSnapshot(market: Market, db: Reader) {
  const { data: run, error } = await db
    .from("screener_runs")
    .select("run_date")
    .eq("market", market.code)
    .gt("row_count", 0)
    .order("run_date", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw new Error(error.message);
  if (!run) return [];
  return readAll<{ symbol: string; company: string | null; stage: string | null; days_in_stage: number | null; pct_change_1d: number | null }>(
    (from, to) =>
      db
        .from("screener_snapshot")
        .select("symbol, company, stage, days_in_stage, pct_change_1d")
        .eq("market", market.code)
        .eq("run_date", run.run_date)
        .order("symbol")
        .range(from, to),
  );
}
