"use client";

import { useState, type ComponentProps } from "react";

import { PriceChart } from "@/components/stock/price-chart";
import { TradingViewChart } from "@/components/stock/tradingview-chart";
import { SegmentedControl } from "@/components/segmented-control";
import type { MarketCode } from "@/lib/markets";

const VIEWS = [
  { value: "line", label: "Line" },
  { value: "candles", label: "Candles" },
] as const;

type View = (typeof VIEWS)[number]["value"];

/**
 * The stock page's chart: our own line (live point, averages, stage markers)
 * first, TradingView's candles one switch away where it serves the stock; the
 * line alone where it has no symbol for it.
 */
export function StockChart({
  tvSymbol,
  market,
  ...line
}: { tvSymbol: string | null; market: MarketCode } & ComponentProps<typeof PriceChart>) {
  const [view, setView] = useState<View>("line");
  if (!tvSymbol) return <PriceChart {...line} />;
  return (
    <div className="space-y-3">
      <SegmentedControl label="Chart type" value={view} onChange={setView} options={[...VIEWS]} />
      {view === "candles" ? (
        <TradingViewChart symbol={tvSymbol} market={market} />
      ) : (
        <PriceChart {...line} />
      )}
    </div>
  );
}
