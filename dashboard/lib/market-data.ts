import "server-only";

import { gunzipSync } from "node:zlib";

import { getCloudflareContext } from "@opennextjs/cloudflare";

import type { MarketCode } from "@/lib/markets";
import { sharedMemo } from "@/lib/shared-memo.mjs";
import { createClient } from "@/lib/supabase/server";

/**
 * Reads from the private `market-data` Storage bucket.
 *
 * Chart price series and snapshot payloads live there as gzip JSON objects
 * rather than in Postgres: the free database stops accepting writes at 500 MB,
 * and Storage has its own 1 GB under the same auth. Every read runs as the signed-in viewer, so the
 * bucket's `dashboard_has_access()` policy applies exactly as the table
 * policies do (storage/market_data_storage.sql).
 */

export const MARKET_DATA_BUCKET = "market-data";

/** Parallel downloads for a many-symbol read, so a long window stays bounded. */
const DOWNLOAD_CONCURRENCY = 24;

export const priceCalendarPath = (market: MarketCode) => `price-series/${market}/calendar.json.gz`;
export const priceSeriesPath = (market: MarketCode, symbol: string) =>
  `price-series/${market}/symbols/${symbol}.json.gz`;

/** A snapshot row's complete source record, written beside its run by the publisher. */
export const snapshotPayloadPath = (market: MarketCode, runDate: string, symbol: string) =>
  `snapshot-payload/${market}/${runDate}/${symbol}.json.gz`;

type Supabase = Awaited<ReturnType<typeof createClient>>;

/** The slice of R2's bucket API used here (the worker types are not a dependency). */
type R2Bucket = { get(key: string): Promise<{ arrayBuffer(): Promise<ArrayBuffer> } | null> };

/** The MARKET_DATA binding, or null off Cloudflare (local development) or before it is bound. */
function r2Bucket(): R2Bucket | null {
  try {
    return ((getCloudflareContext().env as Record<string, unknown>).MARKET_DATA as R2Bucket | undefined) ?? null;
  } catch {
    return null;
  }
}

const unzip = <T>(buffer: Buffer) => JSON.parse(gunzipSync(buffer).toString("utf8")) as T;

/** From R2; null when there is no binding, no object, or it cannot be read (the caller then asks Supabase). */
async function readFromR2<T>(path: string): Promise<T | null> {
  const bucket = r2Bucket();
  if (!bucket) return null;
  try {
    const object = await bucket.get(path);
    if (!object) {
      console.warn(`market-data R2 miss, falling back to Supabase: ${path}`);
      return null;
    }
    return unzip<T>(Buffer.from(await object.arrayBuffer()));
  } catch (cause) {
    console.warn(`market-data R2 read failed, falling back to Supabase: ${path}`, cause instanceof Error ? cause.message : cause);
    return null;
  }
}

/**
 * Objects this instance has read lately. A stock page asks for three on every
 * request, and each R2 read is a network round trip; the objects change at most
 * once an evening. Raw payloads are kept (ratings included), which is safe: the
 * memo is server memory and getStock redacts for the viewer after the read.
 */
const objectMemo = sharedMemo<unknown>(300_000, 40);

/** One object, unzipped and parsed; null when it is missing or unreadable. */
export function readMarketObject<T>(supabase: Supabase, path: string): Promise<T | null> {
  return objectMemo(path, () => loadMarketObject<T>(supabase, path), (value) => value !== null) as Promise<T | null>;
}

async function loadMarketObject<T>(supabase: Supabase, path: string): Promise<T | null> {
  const started = Date.now();
  const fromR2 = await readFromR2<T>(path);
  if (fromR2 !== null) {
    console.log(`market-data R2 ${Date.now() - started} ms: ${path}`);
    return fromR2;
  }
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
    return unzip<T>(Buffer.from(await data.arrayBuffer()));
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
