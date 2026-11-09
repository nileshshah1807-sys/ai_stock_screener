/**
 * Which cards the Home page offers, by market and by whether the viewer
 * watches anything. Plain data, so the rule is tested and the page only
 * renders what it is handed.
 *
 * `scope` "watchlist" cards read the viewer's lists and show only when they
 * have some; "all" cards show to everyone. `markets` lists where a card has
 * data at all: NSE alone has shareholding patterns and bulk/block deals.
 */
export const HOME_CARDS = [
  { id: "since", scope: "watchlist", markets: ["NSE", "US"] },
  { id: "results-in", scope: "watchlist", markets: ["NSE", "US"] },
  { id: "shareholding", scope: "watchlist", markets: ["NSE"] },
  { id: "deals", scope: "watchlist", markets: ["NSE"] },
  { id: "coming-up", scope: "watchlist", markets: ["NSE", "US"] },
  { id: "watchlist-today", scope: "watchlist", markets: ["NSE", "US"] },
  { id: "pulse", scope: "all", markets: ["NSE", "US"] },
  { id: "movers", scope: "all", markets: ["NSE", "US"] },
  { id: "breadth", scope: "all", markets: ["NSE", "US"] },
  { id: "results-season", scope: "all", markets: ["NSE", "US"] },
  { id: "lined-up", scope: "all", markets: ["NSE", "US"] },
];

/**
 * @param {"NSE" | "US"} market
 * @param {boolean} watching whether the viewer has any watchlist symbols
 * @returns {string[]} card ids in page order
 */
export function cardsFor(market, watching) {
  return HOME_CARDS.filter(
    (card) => card.markets.includes(market) && (card.scope === "all" || watching),
  ).map((card) => card.id);
}

/**
 * The query keys the screener reads (`parseFilters`, lib/filters.ts). Only a
 * link carrying one of these is an old screener link; `/ind?utm_source=x`
 * stays on Home.
 */
export const SCREENER_QUERY_KEYS = new Set([
  "q", "rating", "sector", "minScore", "maxScore", "actionable", "buyEligible",
  "excludeCapped", "transcript", "redFlags", "minQuality", "minMomentum",
  "eligibility", "aboveMa200", "stage", "listing", "minRs", "minCapCr",
  "sort", "dir", "page", "cols", "density",
]);

/** Whether a query string means an old screener link (filters, sort, page). */
export function isScreenerQuery(query) {
  return Object.keys(query).some((key) => SCREENER_QUERY_KEYS.has(key));
}

/** `/ind?rating=BUY` -> the same query on the screener's own path. */
export function screenerRedirect(path, query) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    for (const one of Array.isArray(value) ? value : [value]) {
      if (one !== undefined) params.append(key, one);
    }
  }
  const text = params.toString();
  return `${path}/screener${text ? `?${text}` : ""}`;
}

/**
 * Where a card sits: the market band at the top, the dated strip under it, or
 * the content-sized columns. Everything else flows in columns, so a card is as
 * tall as what it holds and no neighbour is stretched to match it.
 */
export const HERO_CARDS = ["pulse", "breadth"];
export const STRIP_CARDS = ["coming-up"];

/** @param {string[]} ids */
export function columnCards(ids) {
  return ids.filter((id) => !HERO_CARDS.includes(id) && !STRIP_CARDS.includes(id));
}

/**
 * The largest magnitude among values, so bars in one card share a scale. A
 * card of nothing but zeros scales to 1 rather than dividing by zero.
 *
 * @param {(number | null | undefined)[]} values
 */
export function barScale(values) {
  const peak = Math.max(0, ...values.filter(Number.isFinite).map(Math.abs));
  return peak || 1;
}

/** Bar length as a share of the scale, 0-100, never past it. */
export function barShare(value, scale) {
  return Number.isFinite(value) ? Math.min(100, (Math.abs(value) / scale) * 100) : 0;
}

/**
 * Dated events grouped by day for the timeline, soonest first.
 *
 * @template {{ event_date: string }} E
 * @param {E[]} events
 * @returns {{ date: string, events: E[] }[]}
 */
export function groupEventsByDate(events) {
  const days = new Map();
  for (const event of events) days.set(event.event_date, [...(days.get(event.event_date) ?? []), event]);
  return [...days].sort(([a], [b]) => a.localeCompare(b)).map(([date, list]) => ({ date, events: list }));
}
