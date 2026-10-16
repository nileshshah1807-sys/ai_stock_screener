import Link from "next/link";
import type { Metadata } from "next";

import { ConcallRow } from "@/components/concalls/concall-row";
import { EventFilterBar } from "@/components/filters/event-filter-bar";
import { LiveSearch } from "@/components/filters/live-search";
import { Reveal } from "@/components/motion";
import { getConcalls } from "@/lib/concalls";
import { STANCE_FILTERS, groupByCallDate, searchTerm } from "@/lib/concalls.mjs";
import { loadFeedFilters } from "@/lib/feed-filters";
import { formatDate } from "@/lib/format";
import { marketFromSlug, marketPath } from "@/lib/markets";
import { getCompanyFacts } from "@/lib/queries";

export const metadata: Metadata = { title: "Concalls" };
export const dynamic = "force-dynamic";

const FEED_LIMIT = 150;

const FACETS = [{ param: "stance", label: "Mgmt Sentiment", options: STANCE_FILTERS }];

/**
 * Earnings calls, newest first, grouped by the day each was held.
 *
 * A call appears the evening it is held, read from the recording the company
 * files with the exchange, and says so. When the company files its own
 * transcript, days later, the same row reads from that and keeps its day.
 * What each row shows is what the screener already scores from: the tone of
 * the call and the outlook it stated.
 *
 * Filtered by the bar Notifications uses (`lib/event-filters.mjs`), and like
 * it opens above a market-cap floor: every filter is in the URL, the search
 * included, so a result can be bookmarked.
 *
 * NSE only for now: there is no recording or transcript source for the US.
 */
export default async function ConcallsPage({
  params,
  searchParams,
}: PageProps<"/[market]/concalls">) {
  const market = marketFromSlug((await params).market)!;
  const query = await searchParams;

  const feed = await loadFeedFilters(market.code, query, { defaultScope: "all", facets: FACETS });
  const search = searchTerm(query.q);
  const filtered = Boolean(search) || !feed.isDefault;

  const [calls, facts] = await Promise.all([
    getConcalls(market.code, {
      symbols: feed.symbols,
      search,
      stances: feed.filters.facets.stance,
      limit: FEED_LIMIT,
    }),
    // Already read for the filter bar; React's cache() makes this free.
    getCompanyFacts(market.code),
  ]);
  const logos = new Map((facts ?? []).map((fact) => [fact.symbol, fact.logo_domain]));
  const groups = groupByCallDate(calls);

  const base = marketPath(market.slug, "/concalls");

  return (
    <div className="space-y-4 px-4 py-5 sm:px-6">
      <div>
        <h1 className="text-title font-semibold">Concalls</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          {market.code === "NSE"
            ? "Earnings calls the day they are held. A call is first read from the recording the company files that evening, then from its transcript once that is filed. Open a highlight for the sentence it came from."
            : `Earnings calls are read for NSE only; there is no recording or transcript source for ${market.label} yet.`}
        </p>
      </div>

      <LiveSearch
        label="Search calls by company or symbol"
        placeholder="Search a company or symbol"
        className="max-w-sm"
      />

      <EventFilterBar {...feed.bar} />

      {groups.length ? (
        <Reveal className="space-y-4">
          {groups.map((group) => (
            <section key={group.date} className="panel overflow-hidden">
              <h2 className="flex items-center gap-2 border-b px-4 py-3 text-base font-semibold tracking-[-0.011em]">
                {formatDate(group.date)}
                <span className="tabular ml-auto font-mono text-xs font-normal text-muted-foreground">
                  {group.calls.length}
                </span>
              </h2>
              <ul className="divide-y">
                {group.calls.map((call) => (
                  <li key={`${call.symbol}:${call.quarter}`}>
                    <ConcallRow call={call} logoDomain={logos.get(call.symbol)} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
          {calls.length === FEED_LIMIT ? (
            <p className="text-center text-xs text-muted-foreground">
              Showing the latest {FEED_LIMIT} calls. Search or filter to see further back.
            </p>
          ) : null}
          <p className="max-w-3xl border-t pt-4 text-xs leading-relaxed text-muted-foreground">
            Outlook starts at 50 and moves only on what the call stated &mdash; guidance, order
            book, capacity, demand, margins &mdash; so 50 means nothing was scored, not average; the
            typical call scores about 66. Management stance is the outlook in a word, against that
            typical call: Bullish from 78, Optimistic from 68, Neutral from 58, Cautious from 48,
            Bearish below; hover it for the statement that moved the score most that way. A call
            whose outlook verified nothing shows a dash. A call read from its recording has no
            speaker labels and its figures are as the speech model heard them.
          </p>
        </Reveal>
      ) : (
        <div className="panel px-5 py-10 text-center">
          <p className="text-sm font-medium">
            {search
              ? `No calls match \u201c${search}\u201d.`
              : feed.scoped
                ? "No recent calls for the companies on your watchlists."
                : feed.isDefault
                  ? "No calls yet."
                  : "No calls match these filters."}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {market.code !== "NSE"
              ? "Calls are read for NSE only."
              : filtered
                ? "Calls go back about six months."
                : "Calls appear here the evening they are held, once the company files its recording."}
          </p>
          {filtered ? (
            <Link
              href={base}
              className="mt-3 inline-block rounded text-xs font-medium underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Clear search and filters
            </Link>
          ) : null}
        </div>
      )}
    </div>
  );
}
