import "server-only";

import { gunzipSync } from "node:zlib";

import type { MarketCode } from "@/lib/markets";
import { createClient } from "@/lib/supabase/server";

/**
 * Reads from the private `market-data` Storage bucket.
 *
 * Chart price series live there as gzip JSON objects rather than in Postgres:
 * the free database stops accepting writes at 500 MB, and Storage has its own
 * 1 GB under the same auth. Every read runs as the signed-in viewer, so the
 * bucket's `dashboard_has_access()` policy applies exactly as the table
 * policies do (storage/market_data_storage.sql).
 */

export const MARKET_DATA_BUCKET = "market-data";

/** Parallel downloads for a many-symbol read, so a long window stays bounded. */
const DOWNLOAD_CONCURRENCY = 24;

export const priceCalendarPath = (market: MarketCode) => `price-series/${market}/calendar.json.gz`;
export const priceSeriesPath = (market: MarketCode, symbol: string) =>
  `price-series/${market}/symbols/${symbol}.json.gz`;

type Supabase = Awaited<ReturnType<typeof createClient>>;

/** One object, unzipped and parsed; null when it is missing or unreadable. */
export async function readMarketObject<T>(supabase: Supabase, path: string): Promise<T | null> {
  const { data, error } = await supabase.storage.from(MARKET_DATA_BUCKET).download(path);
  if (error || !data) {
    // A symbol the publisher has not reached has no object; that is a gap,
    // not a failure, and is common enough not to log.
    if (error && !/not.?found|404/i.test(error.message)) {
      console.error(`readMarketObject(${path}) failed`, error.message);
    }
    return null;
  }
  try {
    const buffer = Buffer.from(await data.arrayBuffer());
    return JSON.parse(gunzipSync(buffer).toString("utf8")) as T;
  } catch (cause) {
    console.error(`readMarketObject(${path}) could not be decoded`, cause);
    return null;
  }
}

/** Many objects, `DOWNLOAD_CONCURRENCY` at a time; missing ones are omitted. */
export async function readMarketObjects<T>(
  supabase: Supabase,
  paths: Map<string, string>,
): Promise<Map<string, T>> {
  const entries = [...paths];
  const found = new Map<string, T>();
  let next = 0;
  const worker = async () => {
    while (next < entries.length) {
      const [key, path] = entries[next++];
      const value = await readMarketObject<T>(supabase, path);
      if (value !== null) found.set(key, value);
    }
  };
  await Promise.all(Array.from({ length: Math.min(DOWNLOAD_CONCURRENCY, entries.length) }, worker));
  return found;
}
