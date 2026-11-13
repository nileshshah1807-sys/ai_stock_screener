import { NextResponse, type NextRequest } from "next/server";

import { bearerMatches } from "@/lib/bearer.mjs";
import { getDigest } from "@/lib/digest";
import { DEFAULT_MARKET, marketFromSlug } from "@/lib/markets";

export const dynamic = "force-dynamic";

/**
 * Today's results, calls, breadth and coming results for one market
 * (`?market=ind|us`), for the post-ideas routine, which carries no session.
 *
 * Not public: the data licence is undecided, so the caller must send
 * `Authorization: Bearer $DIGEST_TOKEN`. The shape is fixed in lib/digest.mjs
 * and carries no rating, rank, score or return.
 */
export async function GET(request: NextRequest) {
  if (!bearerMatches(request.headers.get("authorization"), process.env.DIGEST_TOKEN)) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const market = marketFromSlug(request.nextUrl.searchParams.get("market")) ?? DEFAULT_MARKET;
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: market.timezone }).format(new Date());
  const digest = await getDigest(market, today);
  if (digest === undefined) return NextResponse.json({ error: "unavailable" }, { status: 503 });
  return NextResponse.json(digest, { headers: { "Cache-Control": "private, no-store" } });
}
