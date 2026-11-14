/**
 * Who is on each market's list and which factors it is measured on, as the page says it.
 * The US run has no transcript sentiment, so it names no management guidance.
 */
const MARKETS = {
  NSE: { universe: "NSE- and BSE-listed", factors: "quality, growth, value, momentum, risk and management guidance" },
  US: { universe: "S&P 1500", factors: "quality, growth, value, momentum and risk" },
};

/**
 * One or two plain sentences at the top of the screener: what the list is, what
 * it is measured on and when it updates. Says nothing about a rank or a rating:
 * the viewer ranks the list by their own score (lib/ratings.mjs).
 */
export function screenerIntro(marketCode) {
  const { universe, factors } = MARKETS[marketCode] ?? MARKETS.US;
  return `${universe} companies, measured daily on ${factors}. Rank them by your own score. Updated every evening after the market closes.`;
}
