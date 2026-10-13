import "server-only";

import type { EventFilterFacet } from "@/components/filters/event-filter-bar";
import {
  feedSymbols,
  industryOptions,
  isDefaultView,
  parseEventFilters,
  eventFilterEntries,
} from "@/lib/event-filters.mjs";
import type { MarketCode } from "@/lib/markets";
import { getCompanyFacts } from "@/lib/queries";
import { getWatchlists } from "@/lib/watchlists";

/**
 * Everything a feed page needs to be filtered by the shared bar: the filters
 * its URL spells, the symbols to read the feed for, and the bar's props.
 *
 * One call per page, so Notifications, Concalls and whatever feed comes next
 * read the same URL the same way and differ only in their default scope and
 * their own facets.
 */
export async function loadFeedFilters(
  market: MarketCode,
  query: Record<string, string | string[] | undefined>,
  { defaultScope, facets = [] }: { defaultScope: "all" | "watchlists"; facets?: EventFilterFacet[] },
) {
  const [lists, companies] = await Promise.all([getWatchlists(market), getCompanyFacts(market)]);
  // A list with nothing on it scopes a feed to nothing; it is not offered.
  const watchlists = lists.filter((list) => list.symbols.length);
  const context = { market, listIds: watchlists.map((list) => list.id), defaultScope, facets };
  const filters = parseEventFilters(query, context);

  return {
    filters,
    /** The symbols to read the feed for; null for the whole market. */
    symbols: feedSymbols(filters, watchlists, companies, market),
    /** Whether the feed is scoped to the viewer's watchlists. */
    scoped: filters.lists.length > 0,
    isDefault: isDefaultView(filters, context),
    /** The filters as search-param pairs, for a form that must carry them. */
    entries: eventFilterEntries(filters, context),
    bar: {
      market,
      filters,
      defaultScope,
      facets,
      industries: industryOptions(companies),
      watchlists: watchlists.map((list) => ({
        value: list.id,
        label: list.name,
        count: list.symbols.length,
      })),
      factsAvailable: companies !== null,
    },
  };
}
