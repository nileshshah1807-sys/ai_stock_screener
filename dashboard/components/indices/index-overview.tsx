"use client";

import { useMemo, useState } from "react";

import { IndexChart } from "@/components/market/index-chart";
import { ScrubContext, type ChartPoint } from "@/components/market/breadth-chart";
import { SegmentedControl } from "@/components/segmented-control";
import { TickFlash } from "@/components/tick-flash";
import { formatPercent } from "@/lib/format";
import { isLive, liveOverlay, quoteTime } from "@/lib/live-quotes.mjs";
import { RANGES, decodeRow, indexPoints, rangeStart, sliceFrom } from "@/lib/market-breadth.mjs";
import type { Market } from "@/lib/markets";
import type { BreadthRow } from "@/lib/queries";
import { useLiveQuotes, useNow } from "@/lib/use-live-quotes";
import { cn } from "@/lib/utils";

const DEFAULT_RANGE = "1Y";

/**
 * An index's level over time: the Market page's chart for it, larger, with a
 * range of its own and today's live level as the last point.
 *
 * Only for an index with a published level history; one without (Nifty Bank,
 * Nifty Next 50) shows its live level in the heading instead (IndexLevel).
 */
export function IndexOverview({
  market,
  name,
  row,
}: {
  market: Market;
  name: string;
  row: BreadthRow;
}) {
  const [range, setRange] = useState(DEFAULT_RANGE);
  const [scrub, setScrub] = useState<string | null>(null);
  const now = useNow();

  const points = useMemo(() => indexPoints(decodeRow(row)) as ChartPoint[], [row]);
  const last = points.at(-1)?.time;
  const lookup = useLiveQuotes(market.code, [name], "index");
  const quote = liveOverlay(lookup(name), last);

  const { from, to } = useMemo(() => {
    const end = [last, quote?.session].filter(Boolean).sort().at(-1) ?? "";
    const entry = RANGES.find((item) => item.label === range);
    return {
      from: rangeStart(end, entry?.months ?? null, entry?.days ?? null) ?? points[0]?.time ?? "",
      to: end,
    };
  }, [last, quote?.session, range, points]);
  const shown = useMemo(() => sliceFrom(points, from) as ChartPoint[], [points, from]);

  return (
    <ScrubContext.Provider value={{ time: scrub, setTime: setScrub }}>
      <div className="space-y-3">
        <div className="max-w-full overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <SegmentedControl
            label="Time range"
            value={range}
            onChange={setRange}
            options={RANGES.map((entry) => ({ value: entry.label, label: entry.label }))}
          />
        </div>
        <IndexChart
          name={name}
          points={shown}
          quote={quote}
          market={market}
          now={now}
          from={from}
          to={to}
          linked={false}
        />
      </div>
    </ScrubContext.Provider>
  );
}

/**
 * Today's level and change: in the heading of an index with no chart to
 * carry them, and `compact` on the Indices page's cards. Nothing until a
 * quote has loaded, and nothing for an index the vendor serves no level for.
 */
export function IndexLevel({
  market,
  name,
  batch,
  compact = false,
}: {
  market: Market;
  name: string;
  /**
   * Every index on the page. Each card asks for all of them, so the first
   * request carries the lot and the store folds the rest into it, rather
   * than a request per card.
   */
  batch?: readonly string[];
  compact?: boolean;
}) {
  const quote = useLiveQuotes(market.code, batch ?? [name], "index")(name);
  const now = useNow();
  if (!quote) return null;
  const live = isLive(quote.fetched_at, now);
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <span
        className={cn(
          "numeral font-semibold leading-tight tracking-[-0.02em]",
          compact ? "text-lg" : "text-[1.625rem]",
        )}
      >
        <TickFlash tick={quote.tick}>
          {quote.price.toLocaleString(market.locale, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          })}
        </TickFlash>
      </span>
      <span
        className={cn(
          "tabular font-mono text-sm",
          quote.change_pct === null
            ? "text-muted-foreground"
            : quote.change_pct >= 0
              ? "text-positive"
              : "text-negative",
        )}
      >
        {formatPercent(quote.change_pct, 2, true)}
      </span>
      <span suppressHydrationWarning className="text-xs text-muted-foreground">
        {live ? "Live" : "As of"}{" "}
        {quoteTime(quote.traded_at, market.timezone, market.locale, now)} {market.timezoneLabel}
      </span>
    </div>
  );
}
