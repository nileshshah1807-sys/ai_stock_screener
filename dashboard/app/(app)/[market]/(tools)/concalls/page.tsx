import Link from "next/link";
import type { Metadata } from "next";

import { ConcallRow } from "@/components/concalls/concall-row";
import { PageTitle } from "@/components/page-title";
import { EventFilterBar } from "@/components/filters/event-filter-bar";
import { LiveSearch } from "@/components/filters/live-search";
import { Reveal } from "@/components/motion";
import { UpcomingButton, UpcomingProvider } from "@/components/upcoming/upcoming-sheet";
import { NextConcallTile } from "@/components/upcoming/upcoming-tiles";
import { getConcalls } from "@/lib/concalls";
import { STANCE_FILTERS, groupByCallDate, searchTerm } from "@/lib/concalls.mjs";
import { loadFeedFilters } from "@/lib/feed-filters";
import { formatDate } from "@/lib/format";
import { marketFromSlug, marketPath } from "@/lib/markets";
import { getCompanyFacts } from "@/lib/queries";
import { getUpcoming } from "@/lib/upcoming";
import { upcomingSummary } from "@/lib/upcoming.mjs";
import { getWatchlists } from "@/lib/watchlists";

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

  // The exchange files by India's calendar.
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
  const [calls, facts, upcoming, lists] = await Promise.all([
    getConcalls(market.code, {
      symbols: feed.symbols,
      search,
      stances: feed.filters.facets.stance,
      limit: FEED_LIMIT,
    }),
    // Already read for the filter bar; React's cache() makes this free.
    getCompanyFacts(market.code),
    getUpcoming(market.code, "call", today),
    getWatchlists(market.code),
  ]);
  const next = upcoming ? upcomingSummary(upcoming, today).next : null;
  const watchlists = lists.filter((list) => list.symbols.length).map(({ id, name, symbols }) => ({ id, name, symbols }));
  const logos = new Map((facts ?? []).map((fact) => [fact.symbol, fact.logo_domain]));
  const groups = groupByCallDate(calls);

  const base = marketPath(market.slug, "/concalls");

  const page = (
    <div className="space-y-4 px-4 py-5 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageTitle
          title="Concalls"
          info={
            market.code === "NSE" ? (
              <>
                <p>
                  Earnings calls the day they are held. A call is first read from the recording the company
                  files that evening, then from its transcript once that is filed. Open a highlight for the
                  sentence it came from.
                </p>
                <p>
                  Outlook starts at 50 and moves only on what the call stated (guidance, order book,
                  capacity, demand, margins), so 50 means nothing was scored, not average; the typical call
                  scores about 59. Management stance is the outlook in a word, against that typical call:
                  Bullish from 72, Optimistic from 62, Neutral from 53, Cautious from 45, Bearish below;
                  hover it for the statement that moved the score most that way. A call whose outlook
                  verified nothing shows a dash. A call read from its recording has no speaker labels and its
                  figures are as the speech model heard them.
                </p>
              </>
            ) : undefined
          }
        />
        {upcoming ? <UpcomingButton /> : null}
      </div>

      {next ? (
        <div className="flex flex-wrap gap-3">
          <NextConcallTile next={next} today={today} logoDomain={logos.get(next.symbol)} />
        </div>
      ) : null}

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
  return upcoming ? (
    <UpcomingProvider
      kind="call"
      rows={upcoming}
      today={today}
      lists={watchlists}
      defaultOpen={query.upcoming !== undefined}
    >
      {page}
    </UpcomingProvider>
  ) : (
    page
  );
}
