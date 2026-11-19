/**
 * Tables whose workers write D1 alone (TABLE_BACKEND_D1 in their workflows):
 * Supabase's copy is frozen, so they are read from D1 whatever TABLE_BACKEND
 * says. Kept equal to the tables tools/d1_tables.py leaves out of ORDER that
 * have a Supabase twin.
 */
export const D1_ONLY = new Set(["concall_feed"]);

/**
 * Whether `table` is read off Supabase under the Worker's `TABLE_BACKEND`:
 * unset or "supabase" reads Supabase, "d1" reads every moved table from
 * Cloudflare, a comma list moves only those. A D1-only table always is.
 *
 * @param {string} setting the trimmed TABLE_BACKEND value
 * @param {string} table
 */
export function readsOffSupabase(setting, table) {
  if (D1_ONLY.has(table)) return true;
  if (!setting || setting === "supabase") return false;
  return setting === "d1" || setting.split(",").some((name) => name.trim() === table);
}
