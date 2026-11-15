// Keys of ScreenerFilters (lib/types.ts) that order, page or display the grid without removing a row.
const VIEW_ONLY = new Set(["sort", "dir", "page", "weights", "hiddenColumns", "density"]);

const empty = (value) =>
  value === undefined || value === null || value === false || value === "" ||
  (typeof value === "string" && !value.trim()) ||
  (Array.isArray(value) && !value.length) ||
  (typeof value === "object" && !Array.isArray(value) && Object.values(value).every(empty));

/**
 * Whether these filters can leave out any of the run's rated rows. Errs towards
 * true: a key it does not know counts as a filter, so a new filter is never skipped.
 * @param {Record<string, unknown>} filters
 */
export function narrowsRows(filters) {
  return Object.entries(filters).some(([key, value]) => !VIEW_ONLY.has(key) && !empty(value));
}
