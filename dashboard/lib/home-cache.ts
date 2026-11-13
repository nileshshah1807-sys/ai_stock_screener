import "server-only";

import { unstable_cache } from "next/cache";

import type { Reader } from "@/lib/results";
import { freshValue, sharedMemo } from "@/lib/shared-memo.mjs";
import { createAdminClient } from "@/lib/supabase/admin";

/** Tag on every cached Home read; `revalidateTag` it to drop them all early. */
export const HOME_TAG = "home-cards";

/**
 * A read shared by every viewer and every server instance, kept in Next's
 * Data Cache for `revalidate` seconds.
 *
 * ONLY for market-wide reads that carry nothing viewer-specific. The loader is
 * handed the service-role client, which bypasses row-level security, so each
 * one must name its columns (no `select('*')`), filter on `market`, and read
 * no rating column (rank is allowed). Who may see Home is still decided by the
 * route's own access check.
 *
 * A loader that throws is not cached. Returns `undefined` when the service key
 * is not configured, the read failed or the entry is older than `revalidate`
 * (`freshValue`), and the caller falls back to its per-viewer read.
 */
export async function homeCached<T>(
  name: string,
  market: string,
  revalidate: number,
  load: (db: Reader) => Promise<T>,
  extraKey: string[] = [],
): Promise<T | undefined> {
  if (!createAdminClient()) return undefined;
  try {
    const entry = await unstable_cache(
      async () => ({ at: Date.now(), value: await load(createAdminClient() as unknown as Reader) }),
      ["home", name, market, ...extraKey],
      { revalidate, tags: [HOME_TAG, `${HOME_TAG}:${name}`] },
    )();
    return freshValue(entry as { at: number; value: T } | undefined, revalidate);
  } catch (error) {
    console.error(`homeCached ${name} failed`, error instanceof Error ? error.message : error);
    return undefined;
  }
}

/**
 * `homeCached`, else the same read as the viewer. `load` is handed the service
 * role client when cached and nothing when not, and must throw on a failed
 * read when handed one so a failure is never kept.
 */
export async function cachedOr<T>(
  name: string,
  market: string,
  revalidate: number,
  load: (db?: Reader) => Promise<T>,
  extraKey: string[] = [],
): Promise<T> {
  const cached = await homeCached(name, market, revalidate, (db) => load(db), extraKey);
  return cached !== undefined ? cached : load();
}

const kept = sharedMemo<unknown>(60_000, 200);

/**
 * `cachedOr` behind a 60 s per-instance memo: a warm instance answers from
 * memory, a fresh one makes one cross-instance cache read instead of a live
 * query (0.4-1.5 s from a Worker). Same rules as `cachedOr`.
 */
export function sharedRead<T>(
  name: string,
  market: string,
  revalidate: number,
  load: (db?: Reader) => Promise<T>,
  extraKey: string[] = [],
): Promise<T> {
  return kept(`${name}:${market}:${extraKey.join(":")}`, () => cachedOr(name, market, revalidate, load, extraKey)) as Promise<T>;
}

/** A short stable key for a long list (symbols), so a cache key stays small. */
export async function digest(parts: readonly string[]): Promise<string> {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(parts.join("\n")));
  return [...new Uint8Array(bytes).slice(0, 12)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
