import { NextResponse } from "next/server";

import { getViewer } from "@/lib/auth";
import { getLatestRun, getSearchIndex } from "@/lib/queries";

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
export async function GET() {
  const viewer = await getViewer();
  if (!viewer) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const run = await getLatestRun();
  if (!run) {
    return NextResponse.json({ runDate: null, entries: [] });
  }

  const entries = await getSearchIndex(run.run_date, run.row_count);

  return NextResponse.json(
    { runDate: run.run_date, entries },
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
