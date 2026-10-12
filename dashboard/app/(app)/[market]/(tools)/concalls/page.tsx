import Link from "next/link";
import type { Metadata } from "next";

import { ConcallRow } from "@/components/concalls/concall-row";
import { Reveal } from "@/components/motion";
import { getConcalls } from "@/lib/concalls";
import { groupByCallDate } from "@/lib/concalls.mjs";
import { formatDate } from "@/lib/format";
import { marketFromSlug, marketPath } from "@/lib/markets";
import { getWatchedSymbols } from "@/lib/notifications";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "Concalls" };
export const dynamic = "force-dynamic";

const FEED_LIMIT = 150;

/**
 * A filter is a link, not a control with state, as on Notifications: each
 * combination has its own URL, so the page renders on the server with no
 * client code and a filtered view can be bookmarked.
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
 * Earnings calls, newest first, grouped by the day each was held.
 *
 * A call appears the evening it is held, read from the recording the company
 * files with the exchange, and says so. When the company files its own
 * transcript, days later, the same row reads from that and keeps its day.
 * What each row shows is what the screener already scores from: the tone of
 * the call and the outlook it stated.
 *
 * NSE only for now: there is no recording or transcript source for the US.
 */
export default async function ConcallsPage({
  params,
  searchParams,
}: PageProps<"/[market]/concalls">) {
  const market = marketFromSlug((await params).market)!;
  const query = await searchParams;

  const watched = await getWatchedSymbols(market.code);
  const scope = watched.length && query.scope === "watchlists" ? "watchlists" : "all";
  const recordingOnly = query.source === "recording";

  const calls = await getConcalls(market.code, {
    symbols: scope === "watchlists" ? watched : null,
    recordingOnly,
    limit: FEED_LIMIT,
  });
  const groups = groupByCallDate(calls);

  const base = marketPath(market.slug, "/concalls");
  const href = (next: { scope?: string; recording?: boolean }) => {
    const search = new URLSearchParams();
    // Only the non-default is spelled out, so the plain URL is the default view.
    if ((next.scope ?? scope) === "watchlists") search.set("scope", "watchlists");
    if (next.recording ?? recordingOnly) search.set("source", "recording");
    const text = search.toString();
    return text ? `${base}?${text}` : base;
  };

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

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {watched.length ? (
          <nav aria-label="Whose calls" className="flex items-center gap-1.5">
            <FilterLink href={href({ scope: "all" })} active={scope === "all"}>
              All of {market.label}
            </FilterLink>
            <FilterLink href={href({ scope: "watchlists" })} active={scope === "watchlists"}>
              Your watchlists
            </FilterLink>
          </nav>
        ) : null}
        <nav aria-label="Source of the call's text" className="flex items-center gap-1.5">
          <FilterLink href={href({ recording: false })} active={!recordingOnly}>
            Every call
          </FilterLink>
          <FilterLink href={href({ recording: true })} active={recordingOnly}>
            Awaiting transcript
          </FilterLink>
        </nav>
      </div>

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
              Showing the latest {FEED_LIMIT} calls.
            </p>
          ) : null}
          <p className="max-w-3xl border-t pt-4 text-xs leading-relaxed text-muted-foreground">
            Management tone is where the call&rsquo;s tone score stands among the calls of the last
            two seasons, in fifths from Bearish to Bullish. Outlook starts at 50 and moves only on
            what the call stated &mdash; guidance, order book, capacity, demand, margins &mdash; so
            50 means nothing was scored, not average. A call read from its recording has no speaker
            labels and its figures are as the speech model heard them.
          </p>
        </Reveal>
      ) : (
        <div className="panel px-5 py-10 text-center">
          <p className="text-sm font-medium">
            {recordingOnly
              ? "No call is waiting for its transcript."
              : scope === "watchlists"
                ? "No recent calls for the companies on your watchlists."
                : "No calls yet."}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {market.code === "NSE"
              ? "Calls appear here the evening they are held, once the company files its recording."
              : `Calls are read for NSE only.`}
          </p>
        </div>
      )}
    </div>
  );
}
