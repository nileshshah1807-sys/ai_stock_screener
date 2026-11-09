import "server-only";

import { unstable_cache } from "next/cache";

import type { Reader } from "@/lib/results";
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
 * is not configured or the read failed, and the caller falls back to its
 * per-viewer read.
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
    return await unstable_cache(
      async () => load(createAdminClient() as unknown as Reader),
      ["home", name, market, ...extraKey],
      { revalidate, tags: [HOME_TAG, `${HOME_TAG}:${name}`] },
    )();
  } catch (error) {
    console.error(`homeCached ${name} failed`, error instanceof Error ? error.message : error);
    return undefined;
  }
}
