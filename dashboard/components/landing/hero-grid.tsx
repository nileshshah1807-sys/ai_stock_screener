"use client";

import { useState } from "react";

import { SAMPLE_MARKETS, sampleRows } from "@/lib/landing.mjs";
import { cn } from "@/lib/utils";

type MarketKey = keyof typeof SAMPLE_MARKETS;
type Row = { symbol: string; name: string; price: number; day: number; cap: number; pe: number | null; stage: number };

const chip =
  "inline-flex h-8 items-center rounded-md border px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/**
 * A working picture of the screener's grid: the market switch and the Stage 2
 * filter really filter the sample rows. The companies are invented and the
 * caption says so; nothing here is a quote. No rating column is drawn.
 */
export function HeroGrid() {
  const [market, setMarket] = useState<MarketKey>("ind");
  const [stage2, setStage2] = useState(false);
  const sample = SAMPLE_MARKETS[market];
  const rows = sampleRows(market, stage2);

  return (
    <figure className="panel overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b p-3">
        <div role="group" aria-label="Sample market" className="flex gap-1 rounded-md bg-(--glass) p-0.5">
          {(Object.keys(SAMPLE_MARKETS) as MarketKey[]).map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={market === key}
              onClick={() => setMarket(key)}
              className={cn(
                "h-7 rounded px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                market === key ? "bg-(--lens) text-foreground shadow-(--lens-shadow)" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {SAMPLE_MARKETS[key].label}
            </button>
          ))}
        </div>
        <button
          type="button"
          aria-pressed={stage2}
          onClick={() => setStage2((v) => !v)}
          className={cn(chip, stage2 ? "border-brand bg-brand-soft text-brand" : "border-border text-muted-foreground hover:text-foreground")}
        >
          Stage 2 only
        </button>
        <span className="ml-auto text-xs text-muted-foreground tabular-nums" aria-live="polite">
          {rows.length} of {sample.rows.length} shown
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[22rem] text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th scope="col" className="px-3 py-2 font-medium">Stock</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Price</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">1D</th>
              <th scope="col" className="hidden px-3 py-2 text-right font-medium sm:table-cell">Mkt cap</th>
              <th scope="col" className="hidden px-3 py-2 text-right font-medium sm:table-cell">P/E</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Stage</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map((row: Row, i: number) => (
              <tr
                key={`${market}-${row.symbol}`}
                className="border-b last:border-0 motion-safe:animate-rise hover:bg-(--control)"
                style={{ animationDelay: `${i * 50}ms` }}
              >
                <td className="px-3 py-2.5">
                  <span className="font-semibold">{row.symbol}</span>
                  <span className="block max-w-[9rem] truncate text-xs text-muted-foreground">{row.name}</span>
                </td>
                <td className="px-3 py-2.5 text-right">{sample.money(row.price)}</td>
                <td className={cn("px-3 py-2.5 text-right", row.day >= 0 ? "text-positive" : "text-negative")}>
                  {row.day >= 0 ? "+" : "−"}
                  {Math.abs(row.day).toFixed(2)}%
                </td>
                <td className="hidden px-3 py-2.5 text-right sm:table-cell">{sample.cap(row.cap)}</td>
                <td className="hidden px-3 py-2.5 text-right sm:table-cell">{row.pe === null ? "—" : row.pe.toFixed(1)}</td>
                <td className="px-3 py-2.5 text-right">
                  <span className={cn("rounded px-1.5 py-0.5 text-xs font-medium", row.stage === 2 ? "bg-brand-soft text-brand" : "bg-(--control) text-muted-foreground")}>
                    {row.stage}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <figcaption className="border-t px-3 py-2 text-xs text-muted-foreground">
        Sample layout with invented companies, not live data. Try the market switch and the filter.
      </figcaption>
    </figure>
  );
}
