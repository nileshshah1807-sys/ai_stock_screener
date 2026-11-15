import "server-only";

import { getCloudflareContext } from "@opennextjs/cloudflare";

import { sharedMemo } from "@/lib/shared-memo.mjs";

/**
 * The live objects the workers write to R2 beside their tables
 * (storage/dashboard_repository.py, `_cloudflare_put`): `live/{MARKET}/{name}.json`,
 * `{ market, written_at, rows }`, plain JSON. Names: quotes, index-members,
 * calendar, breadth-levels, breadth-members, results-analysis (rows are quarters;
 * `symbols` beside them).
 *
 * They bypass row-level security, so only server code reads them, after the
 * caller has checked the viewer's access (docs/d1_migration_plan.md, access rule).
 */

type R2Bucket = { get(key: string): Promise<{ text(): Promise<string> } | null> };

/** A quote run lands every five minutes; half a minute keeps every viewer on one parse per instance. */
export const LIVE_OBJECT_TTL_MS = 30_000;

const memo = sharedMemo<Record<string, unknown> | null>(LIVE_OBJECT_TTL_MS, 20);

const MARKETS = new Set(["NSE", "US"]);

async function load(market: string, name: string): Promise<Record<string, unknown> | null> {
  const bucket = (getCloudflareContext().env as Record<string, unknown>).MARKET_DATA as R2Bucket | undefined;
  if (!bucket) throw new Error("no MARKET_DATA binding");
  const object = await bucket.get(`live/${market}/${name}.json`);
  if (!object) return null;
  return JSON.parse(await object.text()) as Record<string, unknown>;
}

/** The whole object (`rows` and whatever else its writer puts beside them), read as `readLiveObject`; null when absent. */
export function readLiveEnvelope<T extends Record<string, unknown>>(market: string, name: string): Promise<T | null> {
  if (!MARKETS.has(market)) return Promise.resolve(null);
  return memo(`${market}:${name}`, () => load(market, name), (body) => body !== null) as Promise<T | null>;
}

/** The object's rows, read at most once per LIVE_OBJECT_TTL_MS per instance; null when it is absent. */
export async function readLiveObject(market: string, name: string): Promise<Record<string, unknown>[] | null> {
  const body = await readLiveEnvelope<{ rows?: Record<string, unknown>[] }>(market, name);
  return body ? (body.rows ?? []) : null;
}
