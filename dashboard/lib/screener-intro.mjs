/**
 * Who is on each market's list and which factors rank it, as the page says it.
 * The US run has no transcript sentiment, so it names no management guidance.
 */
const MARKETS = {
  NSE: { universe: "NSE- and BSE-listed", factors: "quality, growth, value, momentum, risk and management guidance" },
  US: { universe: "S&P 1500", factors: "quality, growth, value, momentum and risk" },
};

/**
 * One or two plain sentences at the top of the screener: what the list is, how
 * it is ranked (heaviest first) and when it updates. Says nothing about
 * ratings: non-admins do not see them.
 */
export function screenerIntro(marketCode) {
  const { universe, factors } = MARKETS[marketCode] ?? MARKETS.US;
  return `${universe} companies, ranked daily on ${factors}. Updated every evening after the market closes.`;
}
