import { NextResponse, type NextRequest } from "next/server";

import { getViewer, isAdmin } from "@/lib/auth";
import { readsFromCloudflare } from "@/lib/db/market-repository";
import { LIVE_MOVERS_LIMIT } from "@/lib/live-market";
import { liveBreadthData, liveMarketData, liveQuoteRows, withMoverRatings } from "@/lib/live-data";
import type { MarketCode } from "@/lib/markets";

export const dynamic = "force-dynamic";

const MARKETS = new Set<MarketCode>(["NSE", "US"]);
const MAX_SYMBOLS = 500;
const MAX_LIMIT = 50;
const SCOPES = new Set(["market", "sector", "industry"]);

/**
 * The browser's live reads, once the live objects are read from R2
 * (`TABLE_BACKEND` names live_quotes): `kind` stock (`live_valuation` rows),
 * index (`live_quotes` levels), market (`live_market`) or breadth
 * (`live_breadth`), answered as `{ data }` in the shapes those returned.
 * Signed-in viewers with access only: the objects bypass row-level security.
 * A rating is returned only to an admin, on the movers, as live_market() does.
 */
export async function GET(request: NextRequest) {
  if (!readsFromCloudflare("live_quotes")) return NextResponse.json({ error: "not enabled" }, { status: 404 });
  if (!(await getViewer())) return NextResponse.json({ error: "unauthorized" }, { status: 401 });

  const params = request.nextUrl.searchParams;
  const market = params.get("market") as MarketCode;
  const kind = params.get("kind");
  if (!MARKETS.has(market)) return NextResponse.json({ error: "bad market" }, { status: 400 });

  try {
    const data = await answer(market, kind, params);
    if (data === undefined) return NextResponse.json({ error: "bad request" }, { status: 400 });
    // private: viewers with access only; the objects change every five minutes.
    return NextResponse.json({ data }, { headers: { "Cache-Control": "private, max-age=30" } });
  } catch (error) {
    console.error("api/live failed", kind, error instanceof Error ? error.message : error);
    return NextResponse.json({ error: "read failed" }, { status: 502, headers: { "Cache-Control": "no-store" } });
  }
}

function answer(market: MarketCode, kind: string | null, params: URLSearchParams) {
  if (kind === "stock" || kind === "index") {
    const symbols = params.getAll("s").slice(0, MAX_SYMBOLS);
    return symbols.length ? liveQuoteRows(market, kind, symbols) : undefined;
  }
  if (kind === "market") {
    const limit = Number(params.get("limit") ?? LIVE_MOVERS_LIMIT);
    if (!(Number.isInteger(limit) && limit > 0 && limit <= MAX_LIMIT)) return undefined;
    return liveMarketData(market, limit).then(async (data) => ((await isAdmin()) ? withMoverRatings(market, data) : data));
  }
  if (kind === "breadth") {
    const scope = params.get("scope") ?? "market";
    return SCOPES.has(scope) ? liveBreadthData(market, scope, params.get("name") ?? "") : undefined;
  }
  return undefined;
}
