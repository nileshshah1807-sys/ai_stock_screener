"use client";

import { useMarket } from "@/components/market-provider";
import { TickFlash } from "@/components/tick-flash";
import { MISSING, formatMoney, formatMoneyCompact, formatNumber, formatPercent } from "@/lib/format";
import { isLive, liveOverlay, quoteTime, ratioOverlay } from "@/lib/live-quotes.mjs";
import { cn } from "@/lib/utils";
import { type LiveRatioKey, useLiveQuotes, useNow } from "@/lib/use-live-quotes";

/*
 * The stock page's Price and 1D tiles, live during the session.
 *
 * The server renders the last close as before; these swap in today's quote
 * once it has loaded (see lib/live-quotes.mjs), so the page never waits on
 * it. Both tiles ask for the same symbol and share one request.
 *
 * LiveRatio does the same for P/E, P/B, EV/EBITDA and market cap, wherever
 * one is shown: the ratio at the live price, from `live_valuation`.
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
      <TickFlash tick={quote.tick}>{formatMoney(quote.price, market)}</TickFlash>
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

/** How a ratio is written: to one or two places, a P/E that hides a loss, or money. */
export type RatioFormat = "number1" | "number2" | "positive1" | "money";

function formatRatio(value: number | null, format: RatioFormat, market: ReturnType<typeof useMarket>) {
  if (format === "money") return formatMoneyCompact(value, market);
  if (format === "positive1") return value === null || value <= 0 ? MISSING : value.toFixed(1);
  return formatNumber(value, format === "number2" ? 2 : 1);
}

/**
 * A price ratio at the latest quote (see `ratioOverlay`), else the close's.
 *
 * The close's figure is what the run scored; the live one is display only.
 * A quote with no ratio (no stored basis, a change of unit) keeps the close's.
 */
export function LiveRatio({
  symbol,
  barDate,
  close,
  metric,
  format,
}: {
  symbol: string;
  barDate: string | null;
  close: number | null;
  metric: LiveRatioKey;
  format: RatioFormat;
}) {
  const market = useMarket();
  const quote = ratioOverlay(useLiveQuotes(market.code, [symbol])(symbol), barDate);
  const live = quote?.[metric] ?? null;
  return (
    <span title={live === null ? undefined : "At the latest price, on the latest reported figures."}>
      {formatRatio(live ?? close, format, market)}
    </span>
  );
}
