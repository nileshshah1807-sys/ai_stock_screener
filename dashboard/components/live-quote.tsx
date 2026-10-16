"use client";

import { useMarket } from "@/components/market-provider";
import { formatMoney, formatPercent } from "@/lib/format";
import { isLive, liveOverlay, quoteTime } from "@/lib/live-quotes.mjs";
import { cn } from "@/lib/utils";
import { useLiveQuotes, useNow } from "@/lib/use-live-quotes";

/*
 * The stock page's Price and 1D tiles, live during the session.
 *
 * The server renders the last close as before; these swap in today's quote
 * once it has loaded (see lib/live-quotes.mjs), so the page never waits on
 * it. Both tiles ask for the same symbol and share one request.
 */

function useQuote(symbol: string, barDate: string | null) {
  const market = useMarket();
  const quote = useLiveQuotes(market.code, [symbol])(symbol);
  return { market, quote: liveOverlay(quote, barDate) };
}

export function LivePrice({
  symbol,
  barDate,
  close,
}: {
  symbol: string;
  barDate: string | null;
  close: number | null;
}) {
  const { market, quote } = useQuote(symbol, barDate);
  const now = useNow();
  if (!quote) return <>{formatMoney(close, market)}</>;

  const live = isLive(quote.fetched_at, now);
  const time = quoteTime(quote.traded_at, market.timezone, market.locale, now);
  return (
    <>
      {formatMoney(quote.price, market)}
      <span className="mt-0.5 flex items-center gap-1.5 text-[11px] font-normal text-muted-foreground">
        {live ? (
          <span className="size-1.5 shrink-0 rounded-full bg-positive" aria-hidden />
        ) : null}
        {live ? "Live" : "As of"} {time} {market.timezoneLabel}
      </span>
    </>
  );
}

export function LiveChange({
  symbol,
  barDate,
  change,
}: {
  symbol: string;
  barDate: string | null;
  change: number | null;
}) {
  const { quote } = useQuote(symbol, barDate);
  const value = quote ? quote.change_pct : change;
  return (
    <span
      className={cn(value === null ? "" : value >= 0 ? "text-positive" : "text-negative")}
      title={quote ? "Today so far, against the previous close." : undefined}
    >
      {formatPercent(value, 2, true)}
    </span>
  );
}
