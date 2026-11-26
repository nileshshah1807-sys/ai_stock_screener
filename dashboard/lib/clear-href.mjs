/**
 * The URL an empty list's "Clear" link goes to: the same page with the given
 * params taken off, or with every param taken off when none are named (the
 * filter bar's own "Clear all"). Whatever else is in the URL -- a sort, a view
 * option -- stays, so clearing a search does not also reset the grid.
 *
 * @param {string} pathname
 * @param {string | URLSearchParams} search  The current query, with or without "?".
 * @param {string[]} [drop]  The params to take off; omitted, all of them.
 * @returns {string}
 */
export function clearedHref(pathname, search, drop) {
  if (!drop) return pathname;
  const params = new URLSearchParams(search);
  for (const key of drop) params.delete(key);
  const rest = params.toString();
  return rest ? `${pathname}?${rest}` : pathname;
}
