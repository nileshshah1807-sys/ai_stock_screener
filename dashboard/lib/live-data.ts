import "server-only";

import { liveBreadth, liveMarket, quoteRow, valuation } from "@/lib/live-compute.mjs";
import { LIVE_OBJECT_TTL_MS, readLiveObject } from "@/lib/live-objects";
import type { MarketCode } from "@/lib/markets";
import { getLatestRun, getRatedSymbols } from "@/lib/queries";
import { sharedMemo } from "@/lib/shared-memo.mjs";
import { createClient } from "@/lib/supabase/server";

/**
 * The live reads from the R2 live objects, for `/api/live` and the server
 * render. The caller has checked the viewer's access. Every object is parsed
 * at most once per 30 s per instance (lib/live-objects.ts), so the cost grows
 * with quote runs, not with viewers; only the page's own valuation_basis rows
 * are read per request, by primary key.
 */

// Movers and breadth take ~4 ms of CPU each over a whole market (8,300 quotes, measured
// in Node): kept per instance as long as the objects, so a request is a lookup.
const movers = sharedMemo<ReturnType<typeof liveMarket>>(LIVE_OBJECT_TTL_MS, 20);
const breadth = sharedMemo<ReturnType<typeof liveBreadth>>(LIVE_OBJECT_TTL_MS, 200);

const quotes = async (market: MarketCode) => (await readLiveObject(market, "quotes")) ?? [];

/** `live_quotes` (kind "index", the levels) or `live_valuation` (kind "stock") rows for `symbols`. */
export async function liveQuoteRows(market: MarketCode, kind: "stock" | "index", symbols: string[]) {
  const wanted = new Set(symbols);
  const rows = (await quotes(market)).filter((quote) => quote.kind === kind && wanted.has(String(quote.symbol)));
  if (kind === "index" || !rows.length) return rows.map(quoteRow);
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("valuation_basis")
    .select("symbol, shares_outstanding, net_profit_ttm, book_equity, ebitda_ttm, total_debt, total_cash")
    .eq("market", market)
    .in("symbol", rows.map((row) => String(row.symbol)));
  if (error) throw new Error(`valuation_basis: ${error.message}`);
  const basis = new Map(((data ?? []) as Record<string, unknown>[]).map((row) => [row.symbol, row]));
  return rows.map((quote) => valuation(quote, basis.get(quote.symbol)));
}

/** The `live_market` function's answer: movers by index. */
export function liveMarketData(market: MarketCode, limit: number) {
  return movers(`${market}:${limit}`, () => computeMarket(market, limit));
}

async function computeMarket(market: MarketCode, limit: number) {
  const [rows, members, run] = await Promise.all([quotes(market), readLiveObject(market, "index-members"), getLatestRun(market)]);
  const shown = liveMarket(rows, members ?? [], limit, new Set<string>());
  const picked = shown.indices.flatMap((index) => [...index.gainers, ...index.losers]);
  // Only the movers shown are looked up in the run, not every member.
  const rated = run ? await getRatedSymbols(market, run.run_date, [...new Set(picked.map((row) => row.symbol))]) : new Set<string>();
  for (const row of picked) row.rated = rated.has(row.symbol);
  return shown;
}

/**
 * `data` (shared by every viewer, so never changed) with each mover's rating, for
 * an admin: live_market() returns it to admins, and the R2 objects carry none.
 */
export async function withMoverRatings(market: MarketCode, data: Awaited<ReturnType<typeof liveMarketData>>) {
  const symbols = [...new Set(data.indices.flatMap((index) => [...index.gainers, ...index.losers].map((row) => row.symbol)))];
  const run = symbols.length ? await getLatestRun(market) : null;
  if (!run) return data;
  const supabase = await createClient();
  const { data: rows, error } = await supabase
    .from("screener_snapshot_visible")
    .select("symbol, rating")
    .eq("market", market)
    .eq("run_date", run.run_date)
    .in("symbol", symbols);
  if (error) {
    console.error("withMoverRatings failed", error.message);
    return data; // the movers without badges, as for a viewer
  }
  const rating = new Map(((rows ?? []) as { symbol: string; rating: string | null }[]).map((row) => [row.symbol, row.rating]));
  const rate = <R extends { symbol: string }>(row: R) => ({ ...row, rating: rating.get(row.symbol) ?? null });
  return { ...data, indices: data.indices.map((index) => ({ ...index, gainers: index.gainers.map(rate), losers: index.losers.map(rate) })) };
}

/** The `live_breadth` function's answer for one group. */
export function liveBreadthData(market: MarketCode, scope: string, name: string) {
  return breadth(`${market}:${scope}:${name}`, () => computeBreadth(market, scope, name));
}

async function computeBreadth(market: MarketCode, scope: string, name: string) {
  const supabase = await createClient();
  const [rows, levels, charted] = await Promise.all([
    quotes(market),
    readLiveObject(market, "breadth-levels"),
    supabase.from("market_breadth").select("last_session").eq("market", market).eq("scope", "market").eq("name", "").maybeSingle(),
  ]);
  if (charted.error) throw new Error(`market_breadth: ${charted.error.message}`);
  const session = (charted.data as { last_session?: string } | null)?.last_session ?? null;
  return liveBreadth(rows, levels ?? [], session, scope, name);
}
