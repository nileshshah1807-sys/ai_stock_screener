import Link from "next/link";
import type { Metadata } from "next";
import { ArrowLeft } from "lucide-react";

import { EventFilterBar } from "@/components/filters/event-filter-bar";
import { Reveal } from "@/components/motion";
import { EventRow } from "@/components/notifications/event-row";
import { MarkNotificationsSeen } from "@/components/notifications/mark-seen";
import { loadFeedFilters } from "@/lib/feed-filters";
import { marketFromSlug, marketPath } from "@/lib/markets";
import { getEvents, getSeenAt } from "@/lib/notifications";
import {
  EVENT_KINDS,
  MARKET_TIME_ZONE,
  eventTime,
  groupByDay,
  isUnread,
} from "@/lib/notifications.mjs";

export const metadata: Metadata = { title: "Notifications" };
export const dynamic = "force-dynamic";

const FEED_LIMIT = 200;

const FACETS = [{ param: "kind", label: "Kind", options: EVENT_KINDS }];

/**
 * Everything recorded for this market, newest first, grouped by the exchange's
 * calendar day.
 *
 * Scoped to the viewer's watchlists by default when they have any, for the
 * reason the bell is: in a results season the whole market is hundreds of
 * filings a day, and the reader asked about the companies they follow. The
 * whole market is one click away -- unticking the lists -- and opens above a
 * market-cap floor for the same reason. Every filter is in the URL, so a
 * filtered view can be bookmarked; see `lib/event-filters.mjs`.
 */
export default async function NotificationsPage({
  params,
  searchParams,
}: PageProps<"/[market]/notifications">) {
  const market = marketFromSlug((await params).market)!;
  const query = await searchParams;

  const [feed, seenAt] = await Promise.all([
    loadFeedFilters(market.code, query, { defaultScope: "watchlists", facets: FACETS }),
    getSeenAt(market.code),
  ]);

  const events = await getEvents(market.code, {
    symbols: feed.symbols,
    kinds: feed.filters.facets.kind,
    limit: FEED_LIMIT,
  });
  const timeZone = MARKET_TIME_ZONE[market.code];
  const groups = groupByDay(events, timeZone);

  return (
    <div className="space-y-4 px-4 py-5 sm:px-6">
      <MarkNotificationsSeen slug={market.slug} />

      <div>
        <Link
          href={marketPath(market.slug)}
          className="inline-flex items-center gap-1 rounded-md text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ArrowLeft className="size-3" aria-hidden />
          Back to screener
        </Link>
        <h1 className="mt-2 text-title font-semibold">Notifications</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          {market.code === "NSE"
            ? "Quarterly results as companies file them with the exchange, and earnings-call transcripts as they are published. Checked three times a day."
            : "Quarterly results as the data vendor publishes them, which can be days after the company reports. Checked three times a day."}
        </p>
      </div>

      <EventFilterBar {...feed.bar} />

      {groups.length ? (
        <Reveal className="space-y-4">
          {groups.map((group) => (
            <section key={group.key} className="panel overflow-hidden">
              <h2 className="flex items-center gap-2 border-b px-4 py-3 text-base font-semibold tracking-[-0.011em]">
                {group.label}
                <span className="tabular ml-auto font-mono text-xs font-normal text-muted-foreground">
                  {group.events.length}
                </span>
              </h2>
              <ul className="divide-y">
                {group.events.map((event) => (
                  <li key={event.id}>
                    <EventRow
                      event={event}
                      market={market}
                      unread={isUnread(event, seenAt)}
                      time={eventTime(event.occurred_at, timeZone)}
                    />
                  </li>
                ))}
              </ul>
            </section>
          ))}
          {events.length === FEED_LIMIT ? (
            <p className="text-center text-xs text-muted-foreground">
              Showing the latest {FEED_LIMIT}. Narrow the filters to see further back.
            </p>
          ) : null}
        </Reveal>
      ) : (
        <div className="panel px-5 py-10 text-center">
          <p className="text-sm font-medium">
            {feed.scoped
              ? "Nothing yet for the companies on your watchlists."
              : feed.isDefault
                ? "Nothing recorded yet."
                : "Nothing matches these filters."}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {feed.scoped
              ? `Results and transcripts appear here as they are recorded. Untick the lists under Watchlist for all of ${market.label}.`
              : "Results and transcripts appear here as they are recorded."}
          </p>
        </div>
      )}
    </div>
  );
}
