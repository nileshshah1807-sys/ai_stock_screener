"use client";

import { useMemo } from "react";

import { BreadthChart, type ChartPoint } from "@/components/market/breadth-chart";
import { indexSlug } from "@/lib/indices.mjs";
import { isLive, quoteTime } from "@/lib/live-quotes.mjs";
import { marketPath, type Market } from "@/lib/markets";
import type { LiveQuote } from "@/lib/use-live-quotes";

/**
 * One headline index, with today's live level as its last point when the
 * quote is from a later session than the published closes.
 *
 * On the Market page it links to the index's own page; the index page draws
 * it without the link (`linked={false}`).
 */
export function IndexChart({
  name,
  points,
  quote,
  market,
  now,
  from,
  to,
  linked = true,
}: {
  name: string;
  points: ChartPoint[];
  quote: LiveQuote | null;
  market: Market;
  now: number;
  from: string;
  to: string;
  linked?: boolean;
}) {
  // The quote object is replaced only when a new read lands, so scrubbing
  // keeps handing the chart the same array.
  const withLive = useMemo(() => {
    const last = points.at(-1);
    if (!quote || (last && quote.session <= last.time)) return points;
    return [...points, { time: quote.session, value: quote.price }];
  }, [points, quote]);
  const drawn = withLive !== points && quote !== null;
  const live = drawn
    ? {
        pulsing: isLive(quote.fetched_at, now),
        label: `${isLive(quote.fetched_at, now) ? "Live" : "As of"} ${quoteTime(
          quote.traded_at,
          market.timezone,
          market.locale,
          now,
        )} ${market.timezoneLabel}`,
        tick: quote.tick,
      }
    : undefined;
  return (
    <BreadthChart
      title={name}
      points={withLive}
      from={from}
      to={to}
      unit="level"
      locale={market.locale}
      tone={
        withLive.length > 1 && withLive[withLive.length - 1].value < withLive[0].value
          ? "negative"
          : "positive"
      }
      live={live}
      link={
        linked
          ? {
              href: marketPath(market.slug, `/indices/${indexSlug(name)}`),
              label: "Open",
              title: `Open the ${name} page`,
            }
          : undefined
      }
    />
  );
}
