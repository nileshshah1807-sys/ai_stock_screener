/**
 * Rules for saved views kept in the viewer's account (storage/saved_views_schema.sql).
 * Pure, so the server actions and the tests share them.
 */

import { VIEW_KEYS } from "./view-match.mjs";

/** Per user and market; the schema's trigger enforces the same number. */
export const SAVED_VIEWS_MAX = 50;
const NAME_MAX = 60;
const QUERY_MAX = 2000;

/** @param {unknown} raw */
export function cleanViewName(raw) {
  return String(raw ?? "").trim().replace(/\s+/g, " ").slice(0, NAME_MAX);
}

/**
 * A query reduced to the keys a view owns, so a stored view can carry nothing
 * the screener URL does not. Empty when nothing is left or it is too long.
 * @param {unknown} raw
 */
export function cleanViewQuery(raw) {
  const params = new URLSearchParams(String(raw ?? ""));
  const next = new URLSearchParams();
  for (const key of VIEW_KEYS) {
    for (const value of params.getAll(key)) if (value) next.append(key, value);
  }
  const query = next.toString();
  return query.length <= QUERY_MAX ? query : "";
}

/**
 * The rows that move a browser's views into the account, once.
 *
 * Browser views had no market and showed on every tab, so each goes to every
 * market. A name the account already has in that market keeps the account's
 * copy; of two browser views with one name the later wins; nothing beyond the
 * cap is written.
 *
 * @param {Array<{label: unknown, query: unknown}>} local
 * @param {Record<string, string[]>} existingNames names already stored, by market
 * @param {string[]} markets
 */
export function legacyImportRows(local, existingNames, markets) {
  const byName = new Map();
  for (const view of local) {
    const name = cleanViewName(view.label);
    const query = cleanViewQuery(view.query);
    if (!name || !query) continue;
    byName.delete(name.toLowerCase());
    byName.set(name.toLowerCase(), { name, query });
  }
  const rows = [];
  for (const market of markets) {
    const taken = new Set((existingNames[market] ?? []).map((name) => name.toLowerCase()));
    let room = SAVED_VIEWS_MAX - taken.size;
    for (const [key, view] of byName) {
      if (room <= 0) break;
      if (taken.has(key)) continue;
      rows.push({ market, ...view });
      room -= 1;
    }
  }
  return rows;
}
