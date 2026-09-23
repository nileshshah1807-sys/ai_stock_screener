import { NextResponse, type NextRequest } from "next/server";

import { getViewer } from "@/lib/auth";
import { DEFAULT_MARKET, marketFromSlug } from "@/lib/markets";
import { getLatestRun, getNewListings, getSearchIndex } from "@/lib/queries";

export const dynamic = "force-dynamic";

/**
 * Universe index for the ⌘K typeahead.
 *
 * Served on demand rather than embedded in the screener's RSC payload. At ~2,400
 * entries the index is roughly 180 KB, and shipping it inline meant re-sending
 * all of it on every sort, filter and page change even though it only varies
 * per run. Fetched here, the browser keeps one copy for the day.
 *
 * `private` keeps it out of shared caches -- the rows are identical for every
 * viewer, but only allowlisted viewers may read them, and an intermediary must
 * not be able to serve this to an unauthenticated request.
 */
export async function GET(request: NextRequest) {
  const viewer = await getViewer();
  if (!viewer) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  // Each market has its own universe, so each has its own index. The market is
  // echoed back below for the same reason runDate is: the browser caches this
  // for an hour and must be able to tell whose index it is holding.
  const market =
    marketFromSlug(request.nextUrl.searchParams.get("market")) ?? DEFAULT_MARKET;

  const run = await getLatestRun(market.code);
  if (!run) {
    return NextResponse.json({ market: market.slug, runDate: null, entries: [] });
  }

  const [rated, pending] = await Promise.all([
    getSearchIndex(market.code, run.run_date, run.row_count),
    market.code === "NSE" ? getNewListings(market.code) : Promise.resolve([]),
  ]);
  // Recent listings the run has not rated are searchable too, after every
  // rated name and labelled NEW, so ⌘K never answers "no match" for a company
  // that listed last week. Their page explains why there is no rating.
  const seen = new Set(rated.map((entry) => entry.s));
  const entries = [
    ...rated,
    ...pending
      .filter((row) => !seen.has(row.symbol))
      .map((row) => ({ s: row.symbol, c: row.company ?? "", r: null, g: "NEW", d: null })),
  ];

  return NextResponse.json(
    { market: market.slug, runDate: run.run_date, entries },
    {
      headers: {
        // A run is immutable once published, so the browser can hold this for
        // the rest of the session; a new run changes the URL's implied content
        // via runDate and the next reload picks it up.
        "Cache-Control": "private, max-age=3600, stale-while-revalidate=86400",
      },
    },
  );
}
