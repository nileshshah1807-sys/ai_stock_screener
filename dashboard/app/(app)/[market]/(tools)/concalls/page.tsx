import Link from "next/link";
import type { Metadata } from "next";
import { Search } from "lucide-react";

import { ConcallRow } from "@/components/concalls/concall-row";
import { EventFilterBar } from "@/components/filters/event-filter-bar";
import { Reveal } from "@/components/motion";
import { Input } from "@/components/ui/input";
import { getConcalls } from "@/lib/concalls";
import { STANCE_FILTERS, groupByCallDate, searchTerm } from "@/lib/concalls.mjs";
import { loadFeedFilters } from "@/lib/feed-filters";
import { formatDate } from "@/lib/format";
import { marketFromSlug, marketPath } from "@/lib/markets";

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

  const calls = await getConcalls(market.code, {
    symbols: feed.symbols,
    search,
    stances: feed.filters.facets.stance,
    limit: FEED_LIMIT,
  });
  const groups = groupByCallDate(calls);

  const base = marketPath(market.slug, "/concalls");

  return (
    <div className="space-y-4 px-4 py-5 sm:px-6">
      <div>
        <h1 className="text-title font-semibold">Concalls</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          {market.code === "NSE"
            ? "Earnings calls the day they are held. A call is first read from the recording the company files that evening, or from a third party's transcript where that recording cannot be fetched, then from the company's own transcript once that is filed. Open a highlight for the sentence it came from."
            : `Earnings calls are read for NSE only; there is no recording or transcript source for ${market.label} yet.`}
        </p>
      </div>

      {/*
        A plain GET form: the search is part of the URL like every other
        filter here, so a result can be bookmarked. The hidden fields carry
        the filters already chosen through the submit.
      */}
      <form action={base} method="get" role="search" className="relative max-w-sm">
        <Search
          className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          type="search"
          name="q"
          defaultValue={search}
          placeholder="Search a company or symbol"
          aria-label="Search calls by company or symbol"
          autoComplete="off"
          className="pl-10"
        />
        {feed.entries.map(([name, value]) => (
          <input key={`${name}:${value}`} type="hidden" name={name} value={value} />
        ))}
      </form>

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
                    <ConcallRow call={call} market={market} />
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
            Management stance is how management itself sees what is ahead, as a language model
            read it from the whole call; hover the word for the sentence it rests on. Calls read
            before that question was added show a dash. Outlook starts at 50 and moves only on
            what the call stated &mdash; guidance, order book, capacity, demand, margins &mdash; so
            50 means nothing was scored, not average. A call read from its recording has no speaker
            labels and its figures are as the speech model heard them.
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
