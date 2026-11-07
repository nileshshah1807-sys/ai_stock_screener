import "server-only";

import type { MarketCode } from "@/lib/markets";
import { createClient } from "@/lib/supabase/server";
import { sampleLines } from "@/lib/live-calls.mjs";

/**
 * Reads for the Live now tab and the live call page: `live_call_state` (a
 * call and its state) and `live_call_feed` (its lines), views over `live_calls` and
 * `live_call_lines` (storage/live_calls_schema.sql),
 * read as the signed-in viewer. While the view does not exist (a preview
 * without the schema) a sample call stands in, flagged `sample`, so the page
 * can be seen working. Nothing here is scored.
 */

export type LiveCall = {
  call_id: string;
  symbol: string;
  state: "upcoming" | "live" | "ended";
  started_at: string | null;
  ended_at: string | null;
};

export type LiveLine = { seq: number; start_seconds: number; text: string };

const MISSING_TABLE = new Set(["PGRST205", "42P01"]);
/** PostgREST returns at most this many rows per request; a call holds a few hundred lines. */
const READ_WINDOW = 1000;
const SAMPLE_HEAD_START = 60;

/** The sample is for previews; a production deploy without the tables shows no live calls, never invented ones. */
const SAMPLE_ALLOWED = process.env.VERCEL_ENV !== "production";

/** The sample call: TCS, started a minute ago, so a few lines are already there. */
function sampleCall(market: MarketCode): LiveCall {
  const now = Date.now();
  return {
    call_id: `${market}:TCS:${new Date(now).toISOString().slice(0, 10)}`,
    symbol: "TCS",
    state: "live",
    started_at: new Date(now - SAMPLE_HEAD_START * 1000).toISOString(),
    ended_at: null,
  };
}

/** Calls being listened to now, with `sample` true when they are the stand-in. */
export async function getLiveCalls(market: MarketCode): Promise<{ calls: LiveCall[]; sample: boolean }> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("live_call_state")
    .select("call_id, symbol, state, started_at, ended_at")
    .eq("market", market)
    .eq("state", "live")
    .order("started_at", { ascending: false });
  if (error) {
    if (!MISSING_TABLE.has(error.code)) console.error("getLiveCalls failed", error.message);
    return MISSING_TABLE.has(error.code) && SAMPLE_ALLOWED
      ? { calls: [sampleCall(market)], sample: true }
      : { calls: [], sample: false };
  }
  return { calls: data as LiveCall[], sample: false };
}

/** One call and the lines spoken so far; null when there is no such call. */
export async function getLiveCall(
  market: MarketCode,
  callId: string,
): Promise<{ call: LiveCall; lines: LiveLine[]; sample: boolean } | null> {
  const supabase = await createClient();
  const [state, feed] = await Promise.all([
    supabase
      .from("live_call_state")
      .select("call_id, symbol, state, started_at, ended_at")
      .eq("market", market)
      .eq("call_id", callId)
      .maybeSingle(),
    supabase
      .from("live_call_feed")
      .select("seq, start_seconds, text")
      .eq("call_id", callId)
      .order("seq", { ascending: true })
      .range(0, READ_WINDOW - 1),
  ]);
  const error = state.error ?? feed.error;
  if (error) {
    if (!MISSING_TABLE.has(error.code)) {
      console.error("getLiveCall failed", error.message);
      return null;
    }
    const call = sampleCall(market);
    if (!SAMPLE_ALLOWED || call.call_id !== callId) return null;
    return { call, lines: sampleLines(SAMPLE_HEAD_START), sample: true };
  }
  if (!state.data) return null;
  const lines = (feed.data ?? []).map(({ seq, start_seconds, text }) => ({
    seq: seq as number,
    start_seconds: Number(start_seconds),
    text: text as string,
  }));
  return { call: state.data as LiveCall, lines, sample: false };
}
