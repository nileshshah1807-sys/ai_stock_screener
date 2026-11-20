"use client";

import { useState, type ComponentProps } from "react";

import { PriceChart } from "@/components/stock/price-chart";
import { TradingViewChart } from "@/components/stock/tradingview-chart";
import { SegmentedControl } from "@/components/segmented-control";
import type { MarketCode } from "@/lib/markets";

const VIEWS = [
  { value: "candles", label: "Candles" },
  { value: "line", label: "Line" },
] as const;

type View = (typeof VIEWS)[number]["value"];

/**
 * The stock page's chart: TradingView's candles where it serves the stock,
 * beside our own line (live point, averages, stage markers); the line alone
 * where TradingView has no symbol for it.
 */
export function StockChart({
  tvSymbol,
  market,
  ...line
}: { tvSymbol: string | null; market: MarketCode } & ComponentProps<typeof PriceChart>) {
  const [view, setView] = useState<View>("candles");
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
