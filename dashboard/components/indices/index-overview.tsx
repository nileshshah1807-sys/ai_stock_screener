"use client";

import { useMemo, useState } from "react";

import { CompareLines, CompareList, useCompare, type CompareMember } from "@/components/indices/compare-chart";
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
 *
 * Given `members`, a list beside the chart lays any of them over the index;
 * with one picked the chart turns into a compare chart (CompareLines). A
 * sector's own index has no live quote (`live={false}`).
 */
export function IndexOverview({
  market,
  name,
  row,
  members,
  live = true,
}: {
  market: Market;
  name: string;
  row: Pick<BreadthRow, "sessions" | "series">;
  members?: CompareMember[];
  live?: boolean;
}) {
  const [range, setRange] = useState(DEFAULT_RANGE);
  const [scrub, setScrub] = useState<string | null>(null);
  const now = useNow();

  const points = useMemo(() => indexPoints(decodeRow(row)) as ChartPoint[], [row]);
  const last = points.at(-1)?.time;
  const lookup = useLiveQuotes(live ? market.code : null, live ? [name] : [], "index");
  const compare = useCompare(market);
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

  const overlays = useMemo(
    () =>
      compare.picked.flatMap((entry) => {
        const loaded = compare.loaded[entry.symbol];
        return loaded ? [{ symbol: entry.symbol, slot: entry.slot, points: loaded }] : [];
      }),
    [compare.picked, compare.loaded],
  );

  const chart = overlays.length ? (
    <CompareLines name={name} index={points} members={overlays} from={from} />
  ) : (
    <IndexChart name={name} points={shown} quote={quote} market={market} now={now} from={from} to={to} linked={false} />
  );

  return (
    <ScrubContext.Provider value={{ time: scrub, setTime: setScrub }}>
      <div className={cn(members?.length && "grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]")}>
        <div className="min-w-0 space-y-3">
          <div className="max-w-full overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <SegmentedControl
              label="Time range"
              value={range}
              onChange={setRange}
              options={RANGES.map((entry) => ({ value: entry.label, label: entry.label }))}
            />
          </div>
          {chart}
        </div>
        {members?.length ? (
          <CompareList
            market={market}
            members={members}
            picked={compare.picked}
            loaded={compare.loaded}
            onToggle={compare.toggle}
            onClear={compare.clear}
          />
        ) : null}
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
