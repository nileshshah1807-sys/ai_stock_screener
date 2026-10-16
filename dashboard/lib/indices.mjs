/**
 * Index names in URLs and in search.
 *
 * An index is identified by its label -- "Nifty Smallcap 250", "S&P 500" --
 * which is what `index_members.index_name` and `market_breadth.name` both
 * store. A label has spaces and an ampersand, so the URL carries a slug of
 * it instead, and the page resolves the slug against the market's own list
 * rather than trying to invert it.
 *
 * Kept free of React so `node --test` can exercise it directly.
 */

import { rank } from "./search.mjs";

/** "Nifty Smallcap 250" -> "nifty-smallcap-250"; "S&P 500" -> "sp-500". */
export function indexSlug(name) {
  return name
    .toLowerCase()
    .replace(/&/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/**
 * What readers type for an index that is nothing like its label. Search
 * terms only, never shown: a code printed beside the name would claim an
 * identifier the data never supplied.
 */
const ALIASES = {
  "Nifty 50": ["NIFTY"],
  "Nifty Bank": ["BANKNIFTY"],
  "S&P 500": ["SPX"],
  "Dow Jones Industrial": ["DJIA"],
  "Russell 2000": ["RUT"],
};

/**
 * Indices matching `term`, best first, by the stock search's own tiers.
 *
 * Each index is ranked under its label and every alias, and keeps its best
 * showing. Within a tier the market's own order wins: Nifty 50 before Nifty
 * 500 for "nifty".
 *
 * @template {{name: string}} T
 * @param {T[]} indices in the market's display order
 * @param {string} term
 * @returns {T[]}
 */
export function rankIndices(indices, term) {
  const entries = indices.flatMap((index, position) =>
    [index.name, ...(ALIASES[index.name] ?? [])].map((s) => ({ s, c: index.name, r: position, index })),
  );
  const seen = new Set();
  const out = [];
  for (const entry of rank(entries, term)) {
    if (seen.has(entry.index.name)) continue;
    seen.add(entry.index.name);
    out.push(entry.index);
  }
  return out;
}
