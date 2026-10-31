import "server-only";

import { fixtureEvents } from "@/lib/upcoming-fixtures.mjs";
import type { MarketCode } from "@/lib/markets";
import { createClient } from "@/lib/supabase/server";
import { HORIZON_DAYS, sortUpcoming } from "@/lib/upcoming.mjs";

/**
 * Reads for the Upcoming lists on Results and Concalls.
 *
 * `upcoming_events` is one row per market, kind, symbol and day, filled from
 * the exchange's board-meeting and call notices. It is read as the signed-in
 * viewer, and reads degrade to nothing while the table does not exist, so the
 * pages simply show no Upcoming button. UPCOMING_FIXTURES=1 reads sample rows
 * instead, for developing the UI.
 */

export type UpcomingKind = "results" | "call";

export type UpcomingEvent = {
  kind: UpcomingKind;
  symbol: string;
  company: string | null;
  /** The company's own calendar day, YYYY-MM-DD. */
  event_date: string;
  /** ISO with the IST offset; null for a result, and for a call whose notice named no time. */
  event_time: string | null;
};

const COLUMNS = "kind, symbol, company, event_date, event_time";
/** PostgREST returns at most this many rows per request; peak weeks hold about 900 results. */
const READ_WINDOW = 1000;

function horizon(today: string) {
  return new Date(Date.parse(`${today}T00:00:00Z`) + HORIZON_DAYS * 86_400_000).toISOString().slice(0, 10);
}

/** Events of one kind from `today` on, soonest first; null when they cannot be read. */
export async function getUpcoming(
  market: MarketCode,
  kind: UpcomingKind,
  today: string,
): Promise<UpcomingEvent[] | null> {
  if (market !== "NSE") return null;
  if (process.env.UPCOMING_FIXTURES === "1") {
    return sortUpcoming(fixtureEvents(today).filter((row: UpcomingEvent) => row.kind === kind), today);
  }
  const supabase = await createClient();
  const rows: UpcomingEvent[] = [];
  for (let from = 0; ; from += READ_WINDOW) {
    const { data, error } = await supabase
      .from("upcoming_events")
      .select(COLUMNS)
      .eq("market", market)
      .eq("kind", kind)
      .gte("event_date", today)
      .lte("event_date", horizon(today))
      .order("event_date", { ascending: true })
      .order("symbol", { ascending: true })
      .range(from, from + READ_WINDOW - 1);
    if (error) {
      console.error("getUpcoming failed", error.message);
      return null;
    }
    rows.push(...(data as UpcomingEvent[]));
    if (data.length < READ_WINDOW) break;
  }
  return sortUpcoming(rows, today);
}

/** The date of this company's coming results, or null. */
export async function getUpcomingResultDate(
  market: MarketCode,
  symbol: string,
  today: string,
): Promise<string | null> {
  if (market !== "NSE") return null;
  if (process.env.UPCOMING_FIXTURES === "1") {
    const row = fixtureEvents(today).find((r: UpcomingEvent) => r.kind === "results" && r.symbol === symbol);
    return row?.event_date ?? null;
  }
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("upcoming_events")
    .select("event_date")
    .eq("market", market)
    .eq("kind", "results")
    .eq("symbol", symbol)
    .gte("event_date", today)
    .order("event_date", { ascending: true })
    .limit(1)
    .maybeSingle();
  if (error) {
    console.error("getUpcomingResultDate failed", error.message);
    return null;
  }
  return (data?.event_date as string | undefined) ?? null;
}
