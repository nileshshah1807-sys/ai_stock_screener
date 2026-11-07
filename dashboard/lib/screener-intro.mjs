/** Who is on each market's screener list, as the page says it. */
const UNIVERSE = { NSE: "NSE- and BSE-listed", US: "NYSE- and Nasdaq-listed" };

/**
 * One or two plain sentences at the top of the screener: what the list is, how
 * it is ranked (the factors the landing hero names, heaviest first) and when it
 * updates. Says nothing about ratings: non-admins do not see them.
 */
export function screenerIntro(marketCode) {
  const who = UNIVERSE[marketCode] ?? "Listed";
  return `${who} companies, ranked daily on quality, growth, value, momentum, risk and management guidance. Updated every evening after the market closes.`;
}
