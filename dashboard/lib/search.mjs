/**
 * Ranked match over the pre-shipped universe index.
 *
 * Ordering is deliberate: someone typing "INF" wants INFY, not the first
 * company whose name happens to contain "inf". Exact ticker beats ticker
 * prefix, which beats a word-start in the company name, which beats any
 * substring. Within a tier the better-ranked stock wins.
 *
 * Punctuation is matched loosely, in both directions. Ten NSE tickers carry an
 * ampersand (M&M, J&KBANK, IL&FSENGG) and seven a hyphen (BAJAJ-AUTO), while
 * people type the name without either. So each candidate is also compared with
 * every non-alphanumeric character stripped: "bajaj auto" finds BAJAJ-AUTO and
 * "mm" finds M&M.
 *
 * Initials are matched too, because a house name is often nothing like its
 * ticker. "P&G" is PGHH, listed as "Procter & Gamble Hygiene and Health Care";
 * neither field contains the string "P&G", so no amount of substring matching
 * would ever have found it. Stripped to "PG", it matches the initials of the
 * company's words.
 */

export const MAX_RESULTS = 8;

/** Drop everything that is not a letter or a digit. */
export const squash = (value) =>
  value.replace(/[^A-Z0-9]/gi, "").toUpperCase();

/**
 * Filler words that carry no signal in an abbreviation. "The Jammu & Kashmir
 * Bank" is known as J&K Bank, not TJKB, and almost every Indian listing ends
 * in "Limited".
 */
const FILLER = new Set(["THE", "AND", "OF", "LIMITED", "LTD", "CO", "COMPANY"]);

/**
 * First letter of each meaningful word, e.g.
 * "Procter & Gamble Hygiene and Health Care Limited" -> "PGHHC".
 */
export const initials = (value) =>
  value
    .toUpperCase()
    .split(/[^A-Z0-9]+/)
    .filter((word) => word && !FILLER.has(word))
    .map((word) => word[0])
    .join("");

export function rank(entries, term) {
  const query = term.trim().toUpperCase();
  if (!query) return [];
  // Empty when the query is punctuation only; the loose tiers are then skipped
  // so a stray "&" does not match the whole universe on initials.
  const squashed = squash(query);

  const scored = [];

  for (const entry of entries) {
    const symbol = entry.s.toUpperCase();
    const company = entry.c.toUpperCase();
    const symbolSquashed = squash(symbol);
    const companySquashed = squash(company);

    let tier = -1;
    if (symbol === query || (squashed && symbolSquashed === squashed)) tier = 0;
    else if (
      symbol.startsWith(query) ||
      (squashed && symbolSquashed.startsWith(squashed))
    )
      tier = 1;
    else if (
      company.startsWith(query) ||
      (squashed && companySquashed.startsWith(squashed))
    )
      tier = 2;
    else if (
      new RegExp(`\\b${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(
        company,
      )
    )
      tier = 3;
    // Initials, but only for a query short enough to be an abbreviation --
    // a longer one would collide with unrelated companies.
    else if (
      squashed.length >= 2 &&
      squashed.length <= 5 &&
      initials(company).startsWith(squashed)
    )
      tier = 4;
    else if (
      symbol.includes(query) ||
      company.includes(query) ||
      (squashed &&
        (symbolSquashed.includes(squashed) ||
          companySquashed.includes(squashed)))
    )
      tier = 5;

    if (tier >= 0) scored.push({ entry, tier });
  }

  scored.sort((a, b) => {
    if (a.tier !== b.tier) return a.tier - b.tier;
    return (a.entry.r ?? 1e9) - (b.entry.r ?? 1e9);
  });

  return scored.slice(0, MAX_RESULTS).map((item) => item.entry);
}
