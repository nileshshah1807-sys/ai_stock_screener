/**
 * Read the newest rows of a feed for a set of symbols of any size.
 *
 * A watchlist is a couple of hundred symbols and goes into the query. A filter
 * such as "market cap above a floor" is most of a market, and a thousand
 * symbols do not fit in a request URL -- so past `PUSH_DOWN_MAX` the feed is
 * read newest-first in windows and the rows are kept here instead, until
 * `limit` of them are found or the windows run out.
 *
 * Kept free of the Supabase client so the windowing can be tested directly
 * (see the .test.mjs beside this); `read` builds and runs the actual query.
 */

export const PUSH_DOWN_MAX = 200;
/** PostgREST returns at most this many rows per request. */
const WINDOW = 1000;
/** How far back a filtered feed looks before settling for fewer than `limit`. */
const MAX_WINDOWS = 3;

/**
 * @template T
 * @param {string[] | null} symbols  null for no restriction; empty matches nothing.
 * @param {number} limit
 * @param {(pushed: string[] | null, from: number, to: number) => PromiseLike<{ data: unknown, error: { message: string } | null }>} read
 *   Runs the query for rows `from`..`to` inclusive, restricted to `pushed` when it is given.
 * @returns {Promise<{ rows: T[], error: string | null }>}
 */
export async function readForSymbols(symbols, limit, read) {
  if (symbols && symbols.length === 0) return { rows: [], error: null };

  if (!symbols || symbols.length <= PUSH_DOWN_MAX) {
    const { data, error } = await read(symbols, 0, limit - 1);
    if (error) return { rows: [], error: error.message };
    return { rows: /** @type {T[]} */ (data ?? []), error: null };
  }

  const wanted = new Set(symbols);
  /** @type {T[]} */
  const rows = [];
  for (let index = 0; index < MAX_WINDOWS && rows.length < limit; index += 1) {
    const { data, error } = await read(null, index * WINDOW, (index + 1) * WINDOW - 1);
    // Rows already found are still true; a later window failing only means
    // the feed reaches less far back.
    if (error) return { rows, error: error.message };
    const page = /** @type {Array<T & { symbol: string }>} */ (data ?? []);
    for (const row of page) {
      if (wanted.has(row.symbol) && rows.length < limit) rows.push(row);
    }
    if (page.length < WINDOW) break;
  }
  return { rows, error: null };
}
