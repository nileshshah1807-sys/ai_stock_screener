/**
 * The markets this dashboard serves.
 *
 * Mirrors `screener/markets.py`, which is the source of truth for everything
 * the pipeline does with a market. What lives here is only what the browser
 * needs: the URL segment, the label, and how to render money.
 *
 * Two identifiers, deliberately:
 *
 *  - `slug` is the URL segment, lowercase, because `/nse` reads better than
 *    `/NSE` and a path is not the place to be shouting.
 *  - `code` is what the database stores, uppercase, matching the `market`
 *    column's check constraint.
 *
 * Conflating them would mean a case-folding call at every query site, and one
 * of them would eventually be forgotten.
 */

export const MARKET_SLUGS = ["nse", "us"] as const;

export type MarketSlug = (typeof MARKET_SLUGS)[number];
export type MarketCode = "NSE" | "US";

export type Market = {
  slug: MarketSlug;
  code: MarketCode;
  /** Short label for the market switch and badges. */
  label: string;
  /** Longer name, for tooltips and screen readers. */
  name: string;
  currencySymbol: string;
  locale: string;
  /**
   * Which magnitude convention scales a large figure. Indian sources read
   * crore and lakh; a reader comparing a US market cap against any US source
   * expects billions and millions. Using one for both misreads by orders of
   * magnitude, which is the same reason `format.ts` never used a bare
   * `toLocaleString`.
   */
  scale: "indian" | "western";
  /** Regulator line in the footer disclaimer. */
  advisor: string;
};

export const MARKETS: Record<MarketSlug, Market> = {
  nse: {
    slug: "nse",
    code: "NSE",
    label: "NSE",
    name: "India · National Stock Exchange",
    currencySymbol: "₹",
    locale: "en-IN",
    scale: "indian",
    advisor: "Consult a SEBI-registered advisor.",
  },
  us: {
    slug: "us",
    code: "US",
    label: "US",
    name: "United States · NYSE & Nasdaq",
    currencySymbol: "$",
    locale: "en-US",
    scale: "western",
    advisor: "Consult a registered investment adviser.",
  },
};

export const DEFAULT_MARKET_SLUG: MarketSlug = "nse";
export const DEFAULT_MARKET = MARKETS[DEFAULT_MARKET_SLUG];

export const MARKET_LIST: readonly Market[] = MARKET_SLUGS.map(
  (slug) => MARKETS[slug],
);

export function isMarketSlug(value: unknown): value is MarketSlug {
  return (
    typeof value === "string" &&
    (MARKET_SLUGS as readonly string[]).includes(value.toLowerCase())
  );
}

/**
 * Resolve a `[market]` route parameter, or null when it names no market.
 *
 * Returning null rather than defaulting is deliberate: the layout turns it
 * into a 404. Quietly serving NSE data under `/nyse` would be worse than a
 * missing page, because nothing on screen would say which market it is.
 */
export function marketFromSlug(value: unknown): Market | null {
  if (!isMarketSlug(value)) return null;
  return MARKETS[value.toLowerCase() as MarketSlug];
}

/** Build an in-market path: `marketPath("us", "/movers")` -> `/us/movers`. */
export function marketPath(slug: MarketSlug, path = ""): string {
  const suffix = path === "/" ? "" : path;
  return `/${slug}${suffix}`;
}

/**
 * Swap the market segment of the current path, keeping the destination.
 *
 * Switching market on the Movers page should stay on Movers rather than
 * bouncing to the grid. A stock detail page is the exception -- the same
 * ticker is a different company across markets, and `/us/stocks/RELIANCE` is
 * not a page -- so those fall back to that market's screener.
 */
export function switchMarketPath(pathname: string, next: MarketSlug): string {
  const segments = pathname.split("/").filter(Boolean);
  if (!segments.length || !isMarketSlug(segments[0])) return marketPath(next);

  const rest = segments.slice(1);
  if (rest[0] === "stocks") return marketPath(next);
  return marketPath(next, rest.length ? `/${rest.join("/")}` : "");
}
