"use client";

import { Change } from "@/components/home/change";
import { useMarket } from "@/components/market-provider";
import { Sparkline } from "@/components/home/sparkline";
import { StockIdentity } from "@/components/stock-identity";
import { TickFlash } from "@/components/tick-flash";
import { formatMoney } from "@/lib/format";
import { liveReturns } from "@/lib/home-watch.mjs";
import { useLiveQuotes } from "@/lib/use-live-quotes";

/**
 * One watched stock: live price and 1D from the quote, 1W and 1M from the
 * stored closes with the live price as the latest point, and the month's trend.
 * Before a quote loads (or out of session) it shows the last close's figures.
 */
export function WatchRow({ symbol, closes }: { symbol: string; closes: number[] }) {
  const market = useMarket();
  const quote = useLiveQuotes(market.code, [symbol])(symbol);
  const { week, month, trend } = liveReturns(closes, quote?.price ?? 0);
  const last = quote?.price ?? closes.at(-1) ?? null;

  return (
    <li className="flex items-center gap-3 py-2">
      <StockIdentity symbol={symbol} className="min-w-0 flex-1" />
      <Sparkline values={trend} className="h-5 w-16 shrink-0" />
      <span className="tabular w-20 shrink-0 text-right text-sm">
        <TickFlash tick={quote?.tick}>{formatMoney(last, market)}</TickFlash>
      </span>
      <span className="tabular grid shrink-0 grid-cols-3 gap-2 text-right text-xs">
        <Cell label="1D" value={quote?.change_pct ?? dayChange(closes)} />
        <Cell label="1W" value={week} />
        <Cell label="1M" value={month} />
      </span>
    </li>
  );
}

function Cell({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <span className="w-14">
      <span className="block text-muted-foreground">{label}</span>
      <Change value={value} unit="%" />
    </span>
  );
}

/** Last close against the one before, for the moment before a live quote arrives. */
function dayChange(closes: number[]): number | null {
  const [before, last] = closes.slice(-2);
  return before > 0 && last != null ? (last / before - 1) * 100 : null;
}
