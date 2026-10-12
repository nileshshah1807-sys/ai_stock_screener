import Link from "next/link";
import type { Metadata } from "next";
import { ArrowLeft } from "lucide-react";

import { Reveal } from "@/components/motion";
import { EventRow } from "@/components/notifications/event-row";
import { MarkNotificationsSeen } from "@/components/notifications/mark-seen";
import { marketFromSlug, marketPath } from "@/lib/markets";
import { getEvents, getSeenAt, getWatchedSymbols } from "@/lib/notifications";
import {
  EVENT_KINDS,
  MARKET_TIME_ZONE,
  eventTime,
  groupByDay,
  isUnread,
} from "@/lib/notifications.mjs";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "Notifications" };
export const dynamic = "force-dynamic";

const FEED_LIMIT = 200;

/**
 * A filter is a link, not a control with state: each combination has its own
 * URL, so the page renders on the server with no client code and a filtered
 * view can be bookmarked. Filled when current, recessed otherwise -- the same
 * two states every pill control in the app has.
 */
function FilterLink({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "true" : undefined}
      className={cn(
        "inline-flex h-8 items-center rounded-full px-3 text-xs font-medium",
        "transition-[background-color,color,transform] duration-(--duration-spring-bouncy) ease-(--ease-spring)",
        "active:scale-[0.96] active:duration-(--duration-press) active:ease-out",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
        active
          ? "bg-primary text-primary-foreground"
          : "bg-(--control) text-muted-foreground hover:bg-(--control-hover) hover:text-foreground",
      )}
    >
      {children}
    </Link>
  );
}

/**
 * Everything recorded for this market, newest first, grouped by the exchange's
 * calendar day.
 *
 * Scoped to the viewer's watchlists by default when they have any, for the
 * reason the bell is: in a results season the whole market is hundreds of
 * filings a day, and the reader asked about the companies they follow. The
 * whole market is one click away.
 */
export default async function NotificationsPage({
  params,
  searchParams,
}: PageProps<"/[market]/notifications">) {
  const market = marketFromSlug((await params).market)!;
  const query = await searchParams;

  const [watched, seenAt] = await Promise.all([
    getWatchedSymbols(market.code),
    getSeenAt(market.code),
  ]);
  const kind = EVENT_KINDS.find((item) => item.value === query.kind)?.value ?? null;
  const scope = watched.length && query.scope !== "all" ? "watchlists" : "all";

  const events = await getEvents(market.code, {
    symbols: scope === "watchlists" ? watched : null,
    kind,
    limit: FEED_LIMIT,
  });
  const timeZone = MARKET_TIME_ZONE[market.code];
  const groups = groupByDay(events, timeZone);

  const base = marketPath(market.slug, "/notifications");
  const href = (next: { scope?: string; kind?: string | null }) => {
    const search = new URLSearchParams();
    const nextScope = next.scope ?? scope;
    const nextKind = next.kind === undefined ? kind : next.kind;
    // Only the non-default is spelled out, so the plain URL is the default view.
    if (watched.length && nextScope === "all") search.set("scope", "all");
    if (nextKind) search.set("kind", nextKind);
    const text = search.toString();
    return text ? `${base}?${text}` : base;
  };

  return (
    <div className="space-y-4 px-4 py-5 sm:px-6">
      <MarkNotificationsSeen slug={market.slug} />

      <div>
        <Link
          href={marketPath(market.slug)}
          className="inline-flex items-center gap-1 rounded-full text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {watched.length ? (
          <nav aria-label="Whose notifications" className="flex items-center gap-1.5">
            <FilterLink href={href({ scope: "watchlists" })} active={scope === "watchlists"}>
              Your watchlists
            </FilterLink>
            <FilterLink href={href({ scope: "all" })} active={scope === "all"}>
              All of {market.label}
            </FilterLink>
          </nav>
        ) : null}
        <nav aria-label="Kind of notification" className="flex items-center gap-1.5">
          <FilterLink href={href({ kind: null })} active={kind === null}>
            Everything
          </FilterLink>
          {EVENT_KINDS.map((item) => (
            <FilterLink key={item.value} href={href({ kind: item.value })} active={kind === item.value}>
              {item.label}
            </FilterLink>
          ))}
        </nav>
      </div>

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
              Showing the latest {FEED_LIMIT}. Narrow by kind or to your watchlists to see further back.
            </p>
          ) : null}
        </Reveal>
      ) : (
        <div className="panel px-5 py-10 text-center">
          <p className="text-sm font-medium">
            {scope === "watchlists"
              ? "Nothing yet for the companies on your watchlists."
              : "Nothing recorded yet."}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {scope === "watchlists"
              ? `Results and transcripts appear here as they are recorded. All of ${market.label} is one filter away.`
              : "Results and transcripts appear here as they are recorded."}
          </p>
        </div>
      )}
    </div>
  );
}
