"use client";

import Link from "next/link";

import { useLiveMarket } from "@/components/market/live-movers";
import { useMarket } from "@/components/market-provider";
import { TickFlash } from "@/components/tick-flash";
import { formatPercent } from "@/lib/format";
import { tickerRows } from "@/lib/home.mjs";
import { marketDate } from "@/lib/intraday.mjs";
import { listing } from "@/lib/listing.mjs";
import { LIVE_MOVERS_LIMIT, type LiveMarket, type LiveMover } from "@/lib/live-market";
import { marketPath } from "@/lib/markets";
import { useNow } from "@/lib/use-live-quotes";
import { cn } from "@/lib/utils";

function Item({ row, copy }: { row: LiveMover; copy: boolean }) {
  const market = useMarket();
  const up = row.change_pct >= 0;
  const body = (
    <>
      <span className="font-medium text-foreground">{listing(row.symbol).ticker}</span>
      <TickFlash tick={row.tick} className="tabular font-mono text-muted-foreground">
        {row.price.toLocaleString(market.locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </TickFlash>
      <span className={cn("tabular font-mono", up ? "text-positive" : "text-negative")}>
        {up ? "▲" : "▼"} {formatPercent(row.change_pct, 2, true)}
      </span>
    </>
  );
  const className = "flex items-baseline gap-1.5 whitespace-nowrap rounded text-xs";
  // An index member the screener does not rate has no stock page.
  return row.rated ? (
    <Link
      prefetch={false}
      href={marketPath(market.slug, `/stocks/${encodeURIComponent(row.symbol)}`)}
      tabIndex={copy ? -1 : undefined}
      className={cn(className, "hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring")}
    >
      {body}
    </Link>
  ) : (
    <span className={className}>{body}</span>
  );
}

/**
 * The day's biggest movers in the first index, gliding past under the index
 * tiles: the live movers the Top movers card already polls, gainers then
 * losers. It pauses under the pointer, and stands still (scrolled by hand) for
 * a reader who asks for reduced motion. Nothing before the session's first
 * quotes, so it never shows yesterday's moves as today's.
 */
export function LiveTicker({ initial }: { initial: LiveMarket | null }) {
  const market = useMarket();
  const now = useNow();
  const { data } = useLiveMarket(market, initial, LIVE_MOVERS_LIMIT);
  const { index, rows } = tickerRows(data, marketDate(now, market.timezone));
  if (!rows.length) return null;

  const list = (copy: boolean) => (
    <ul aria-hidden={copy || undefined} className={cn("flex shrink-0 gap-6 pr-6", copy && "motion-reduce:hidden")}>
      {rows.map((row) => (
        <li key={row.symbol}>
          <Item row={row} copy={copy} />
        </li>
      ))}
    </ul>
  );

  return (
    <div
      role="region"
      aria-label={`${index} movers today`}
      className="group mt-4 overflow-hidden border-t border-border pt-3 [mask-image:linear-gradient(to_right,transparent,black_2rem,black_calc(100%-2rem),transparent)] motion-reduce:overflow-x-auto"
    >
      <div className="flex w-max animate-marquee group-hover:[animation-play-state:paused] group-focus-within:[animation-play-state:paused] motion-reduce:animate-none">
        {list(false)}
        {list(true)}
      </div>
    </div>
  );
}
