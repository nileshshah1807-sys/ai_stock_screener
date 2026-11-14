/**
 * The browser client, fetched when first used.
 *
 * supabase-js is ~57 KB gzipped. The live readers only query after the page is
 * hydrated and visible, so importing it statically put it on the critical path
 * of every page that shows live prices (cold mobile load, Nov 2026).
 */
export async function lazyClient() {
  try {
    return (await import("./client")).createClient();
  } catch {
    // Offline for a moment, or a chunk replaced by a deploy: one more try.
    return (await import("./client")).createClient();
  }
}

/** A failed import read as a failed query, which every live reader already survives. */
export const importFailed = (error: unknown) => ({ data: null, error });

/**
 * A live read from `/api/live` (app/api/live/route.ts), once the live objects
 * are read from R2, answered as a query is: `{ data, error }`.
 */
export async function liveApi(params: Record<string, string | readonly string[]>): Promise<{ data: unknown; error: unknown }> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    for (const item of typeof value === "string" ? [value] : value) query.append(key, item);
  }
  try {
    const response = await fetch(`/api/live?${query}`);
    if (!response.ok) return { data: null, error: new Error(`api/live ${response.status}`) };
    return { data: ((await response.json()) as { data: unknown }).data, error: null };
  } catch (error) {
    return { data: null, error };
  }
}
