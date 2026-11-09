"use client";

import Link from "next/link";

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

function Change({ value }: { value: number | null }) {
  return (
    <span
      className={cn(
        "tabular w-16 shrink-0 text-right font-mono text-xs",
        value === null ? "text-muted-foreground" : value >= 0 ? "text-positive" : "text-negative",
      )}
    >
      {formatPercent(value, 2, true)}
    </span>
  );
}

/**
 * The headline indices: level now (the live quote once it is from a later
 * session than the last close) and the change over a day, a week and a
 * month. 1W and 1M are measured from the closes the server sent, to the live
 * level; the status says whether the market is trading.
 */
export function PulseTable({ indices }: { indices: PulseIndex[] }) {
  const market = useMarket();
  const marketDay = useMarketDay();
  const now = useNow();
  const lookup = useLiveQuotes(market.code, indices.map((index) => index.name), "index");
  const open = inSession(now, market, marketDay);

  return (
    <>
      <p suppressHydrationWarning className="mb-1 flex items-center gap-1.5 text-xs text-muted-foreground">
        <span className={cn("size-2 rounded-full", open ? "bg-positive" : "border border-border")} aria-hidden />
        {open ? "Market open" : "Market closed"}
      </p>
      <div className="flex items-center gap-3 pb-1 text-xs text-muted-foreground" aria-hidden>
        <span className="min-w-0 flex-1" />
        <span className="hidden w-24 text-right sm:block">Level</span>
        {["1D", "1W", "1M"].map((label) => (
          <span key={label} className="w-16 shrink-0 text-right">
            {label}
          </span>
        ))}
      </div>
      <ul className="divide-y divide-border">
        {indices.map((index) => {
          const quote = liveOverlay(lookup(index.name), index.last.time);
          const level = quote?.price ?? index.last.value;
          const day = quote ? quote.change_pct : pctChange(index.prev ?? NaN, index.last.value);
          return (
            <li key={index.name}>
              <Link
                href={marketPath(market.slug, `/indices/${indexSlug(index.name)}`)}
                className="flex items-center gap-3 py-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{index.name}</span>
                <span className="tabular hidden w-24 text-right font-mono text-xs sm:block">
                  <TickFlash tick={quote?.tick}>
                    {level.toLocaleString(market.locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </TickFlash>
                </span>
                <Change value={day ?? null} />
                <Change value={pctChange(index.week ?? NaN, level)} />
                <Change value={pctChange(index.month ?? NaN, level)} />
              </Link>
            </li>
          );
        })}
      </ul>
    </>
  );
}
