/** Who is on each market's list, as the page says it. */
const UNIVERSES = {
  NSE: "NSE- and BSE-listed",
  US: "S&P 1500",
};

/**
 * One or two plain sentences at the top of the screener: what the list is, what
 * it is measured on and when it updates. Says nothing about a rank or a rating:
 * the viewer ranks the list by their own score (lib/ratings.mjs).
 */
export function screenerIntro(marketCode) {
  const universe = UNIVERSES[marketCode] ?? UNIVERSES.US;
  return `${universe} companies, measured daily on quality, growth, value, momentum, risk and management guidance. Rank them by your own score. Updated every evening after the market closes.`;
}
