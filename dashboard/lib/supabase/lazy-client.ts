/**
 * The browser client, fetched when first used.
 *
 * supabase-js is ~57 KB gzipped. The live readers only query after the page is
 * hydrated and visible, so importing it statically put it on the critical path
 * of every page that shows live prices (cold mobile load, Nov 2026).
 */
export async function lazyClient() {
  return (await import("./client")).createClient();
}
