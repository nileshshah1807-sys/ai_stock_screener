"use client";

import Link from "next/link";

import { Sparkline } from "@/components/home/sparkline";
import { TickFlash } from "@/components/tick-flash";
import { useMarket, useMarketDay } from "@/components/market-provider";
import { formatPercent } from "@/lib/format";
import { pctChange } from "@/lib/home-market.mjs";
import { indexSlug } from "@/lib/indices.mjs";
import { inSession, liveOverlay } from "@/lib/live-quotes.mjs";
import { marketPath } from "@/lib/markets";
import type { PulseIndex } from "@/lib/home-market";
import { useLiveQuotes, useNow } from "@/lib/use-live-quotes";
import { cn } from "@/lib/utils";

function Change({ label, value }: { label: string; value: number | null }) {
  return (
    <span className="flex items-baseline gap-1">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("tabular font-mono", value === null ? "text-muted-foreground" : value >= 0 ? "text-positive" : "text-negative")}>
        {formatPercent(value, 2, true)}
      </span>
    </span>
  );
}

/**
 * The headline indices as tiles: level now (the live quote once it is from a
 * later session than the last close), the day's change large, the week and
 * month beneath, and a month of closes as a line. 1W and 1M are measured from
 * the closes the server sent, to the live level.
 */
export function PulseTiles({ indices }: { indices: PulseIndex[] }) {
  const market = useMarket();
  const marketDay = useMarketDay();
  const now = useNow();
  const lookup = useLiveQuotes(market.code, indices.map((index) => index.name), "index");
  const open = inSession(now, market, marketDay);

  return (
    <>
      <p suppressHydrationWarning className="mb-3 flex items-center gap-1.5 text-xs text-muted-foreground">
        <span className={cn("size-2 rounded-full", open ? "bg-positive" : "border border-border")} aria-hidden />
        {open ? "Market open" : "Market closed"}
      </p>
      <ul className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {indices.map((index, position) => {
          const quote = liveOverlay(lookup(index.name), index.last.time);
          const level = quote?.price ?? index.last.value;
          const day = quote ? quote.change_pct : pctChange(index.prev ?? NaN, index.last.value);
          const trend = index.trend ?? [];
          return (
            <li key={index.name} className="animate-rise" style={{ animationDelay: `${position * 60}ms` }}>
              <Link
                href={marketPath(market.slug, `/indices/${indexSlug(index.name)}`)}
                className="flex h-full flex-col gap-1 rounded-xl border border-border bg-background/40 p-3 transition-colors duration-(--duration-fast) hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="truncate text-xs font-medium text-muted-foreground">{index.name}</span>
                <span className="tabular font-mono text-base font-semibold sm:text-lg">
                  <TickFlash tick={quote?.tick}>
                    {level.toLocaleString(market.locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </TickFlash>
                </span>
                <span
                  className={cn(
                    "tabular font-mono text-sm font-medium",
                    day == null ? "text-muted-foreground" : day >= 0 ? "text-positive" : "text-negative",
                  )}
                >
                  {formatPercent(day ?? null, 2, true)}
                </span>
                <Sparkline values={trend} className="my-1" />
                <span className="flex justify-between gap-2 text-[11px]">
                  <Change label="1W" value={pctChange(index.week ?? NaN, level)} />
                  <Change label="1M" value={pctChange(index.month ?? NaN, level)} />
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </>
  );
}
