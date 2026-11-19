import { getCloudflareContext } from "@opennextjs/cloudflare";
import { NextResponse, type NextRequest } from "next/server";

import { getViewer } from "@/lib/auth";
import { priceCalendarPath, priceSeriesPath } from "@/lib/market-data";
import type { MarketCode } from "@/lib/markets";

export const dynamic = "force-dynamic";

const MARKETS = new Set<MarketCode>(["NSE", "US"]);
// NSE symbols carry & and -, BSE-only ones .BO.
const SYMBOL = /^[A-Z0-9&._-]{1,30}$/;

type R2Bucket = { get(key: string): Promise<{ body: ReadableStream } | null> };

/**
 * One stock's daily price series (or, with `symbol=calendar`, the shared
 * trading calendar) for the compare chart, straight from R2.
 *
 * The object is gzip JSON; it is decompressed as a stream and passed on
 * without being parsed, so the Worker spends next to no CPU on it (the
 * browser decodes it with lib/price-series.mjs). R2 only: a miss is a 404,
 * never a Supabase read. Signed-in viewers with access only.
 */
export async function GET(request: NextRequest) {
  if (!(await getViewer())) return NextResponse.json({ error: "unauthorized" }, { status: 401 });

  const params = request.nextUrl.searchParams;
  const market = params.get("market") as MarketCode;
  const symbol = (params.get("symbol") ?? "").toUpperCase();
  if (!MARKETS.has(market) || !SYMBOL.test(symbol)) {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }

  let bucket: R2Bucket | undefined;
  try {
    bucket = (getCloudflareContext().env as Record<string, unknown>).MARKET_DATA as R2Bucket | undefined;
  } catch {
    bucket = undefined;
  }
  if (!bucket) return NextResponse.json({ error: "not available" }, { status: 503 });

  const path = symbol === "CALENDAR" ? priceCalendarPath(market) : priceSeriesPath(market, symbol);
  const object = await bucket.get(path);
  if (!object) return NextResponse.json({ error: "not found" }, { status: 404 });

  return new Response(object.body.pipeThrough(new DecompressionStream("gzip")), {
    headers: {
      "Content-Type": "application/json",
      // Viewers with access only; the series changes once an evening.
      "Cache-Control": "private, max-age=3600",
    },
  });
}
