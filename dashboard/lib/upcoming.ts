import "server-only";

import { fixtureRows } from "@/lib/upcoming-fixtures.mjs";
import type { MarketCode } from "@/lib/markets";
import { createClient } from "@/lib/supabase/server";
import { runCompanyNames } from "@/lib/results";
import { eventsFromRows } from "@/lib/upcoming.mjs";

/**
 * Reads for the Upcoming lists on Results and Concalls.
 *
 * `upcoming_events` is one row per stock, filled from the exchange's
 * board-meeting and earnings-call notices: its next result date, and its next
 * call with a time (`next_call_at`) or, when the notice gave none, a date
 * (`next_call_date`). It is read as the signed-in viewer, and reads degrade to
 * nothing while the table does not exist, so the pages simply show no
 * Upcoming button. Company names come from the latest run, as on the Results
 * page. UPCOMING_FIXTURES=1 reads sample rows instead, for
 * developing the UI.
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

const COLUMNS = "symbol, next_result_date, next_call_at, next_call_date";
/** PostgREST returns at most this many rows per request; a peak week holds about 900 stocks. */
const READ_WINDOW = 1000;

/** PostgREST and Postgres codes for a table that is not there yet: nothing to log until it is applied. */
const MISSING_TABLE = new Set(["PGRST205", "42P01"]);

type UpcomingRow = {
  symbol: string;
  next_result_date: string | null;
  next_call_at: string | null;
  next_call_date: string | null;
};

/** Events of one kind from `today` on, soonest first; null when they cannot be read. */
export async function getUpcoming(
  market: MarketCode,
  kind: UpcomingKind,
  today: string,
): Promise<UpcomingEvent[] | null> {
  if (market !== "NSE") return null;
  if (process.env.UPCOMING_FIXTURES === "1") return eventsFromRows(fixtureRows(today), kind, today);
  const names = await runCompanyNames(market);
  const supabase = await createClient();
  const rows: UpcomingRow[] = [];
  for (let from = 0; ; from += READ_WINDOW) {
    const query = supabase.from("upcoming_events").select(COLUMNS).eq("market", market);
    // A call's day is India's: its timestamp is compared from that day's start.
    const { data, error } = await (kind === "results"
      ? query.gte("next_result_date", today)
      : query.or(`next_call_at.gte.${today}T00:00:00+05:30,next_call_date.gte.${today}`)
    )
      .order("symbol", { ascending: true })
      .range(from, from + READ_WINDOW - 1);
    if (error) {
      if (!MISSING_TABLE.has(error.code)) console.error("getUpcoming failed", error.message);
      return null;
    }
    rows.push(...(data as UpcomingRow[]));
    if (data.length < READ_WINDOW) break;
  }
  return eventsFromRows(rows.map((row) => ({ ...row, company: names.get(row.symbol) ?? null })), kind, today);
}

/** The date of this company's coming results, or null. */
export async function getUpcomingResultDate(
  market: MarketCode,
  symbol: string,
  today: string,
): Promise<string | null> {
  if (market !== "NSE") return null;
  if (process.env.UPCOMING_FIXTURES === "1") {
    return eventsFromRows(fixtureRows(today), "results", today).find((event: UpcomingEvent) => event.symbol === symbol)?.event_date ?? null;
  }
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("upcoming_events")
    .select("next_result_date")
    .eq("market", market)
    .eq("symbol", symbol)
    .gte("next_result_date", today)
    .maybeSingle();
  if (error) {
    if (!MISSING_TABLE.has(error.code)) console.error("getUpcomingResultDate failed", error.message);
    return null;
  }
  return (data?.next_result_date as string | undefined) ?? null;
}
