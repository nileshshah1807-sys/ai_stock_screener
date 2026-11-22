"use client";

import { useState } from "react";

import { DivBar } from "@/components/home/bar";
import { flowFormat } from "@/components/market/flow-format";
import { fortnightLabel, fortnightMonth, gridScale, heatFill } from "@/lib/fpi-flows.mjs";
import type { Market } from "@/lib/markets";
import { cn } from "@/lib/utils";

type Period = { start: string; end: string };
type SectorRow = { sector: string; net: number | null; held: number | null; history: (number | null)[]; year: number | null };
export type SectorTable = { latest: Period; periods: Period[]; yearSpan: number; sectors: SectorRow[]; total: SectorRow };

/**
 * FPI net equity investment by sector, from NSDL's fortnightly report
 * (lib/fpi-flows.mjs, sectorFlows): the latest fortnight as a diverging bar,
 * the last six months as a row of cells, the year's sum and what FPIs hold.
 * The cell under the pointer or focus is written out below the table, as the
 * FII/DII bars do, so no figure lives only in a colour. Client-side for that
 * readout alone.
 */
export function FpiSectorFlows({ market, table }: { market: Market; table: SectorTable }) {
  const [active, setActive] = useState<{ row: SectorRow; index: number } | null>(null);
  const { money, signed, tone } = flowFormat(market);
  const scale = gridScale(table);
  // All sectors together run larger than any one: their cells get their own scale.
  const totalScale = Math.max(1, ...table.total.history.map((net) => Math.abs(net ?? 0)));
  const shown = active ?? { row: table.total, index: table.periods.length - 1 };
  const shownPeriod = table.periods[shown.index] ?? table.latest;
  const yearLabel = table.yearSpan >= 24 ? "1Y" : `${table.yearSpan} fortnights`;

  const row = (entry: SectorRow, total = false) => (
    <tr key={entry.sector} className={cn("border-t", total ? "border-border" : "border-border/60")}>
      <th
        scope="row"
        className={cn(
          "sticky left-0 z-10 bg-card py-2 pr-3 text-left text-sm whitespace-nowrap",
          total ? "font-semibold" : "font-medium",
        )}
      >
        {entry.sector}
      </th>
      <td
        className={cn(
          "tabular py-2 pr-3 text-right font-mono text-xs whitespace-nowrap",
          total && "font-semibold",
          tone(entry.net),
        )}
      >
        {signed(entry.net)}
      </td>
      <td className="w-28 py-2 pr-5">{total ? null : <DivBar value={entry.net} scale={scale} />}</td>
      <td className="py-2 pr-5">
        <span className="flex gap-0.5">
          {entry.history.map((net, index) => {
            const period = table.periods[index];
            const on = active?.row === entry && active.index === index;
            return (
              <span
                key={period.end}
                role="img"
                tabIndex={0}
                aria-label={`${entry.sector}, ${fortnightLabel(period.start, period.end)}: ${signed(net)}`}
                onPointerEnter={() => setActive({ row: entry, index })}
                onFocus={() => setActive({ row: entry, index })}
                className={cn(
                  "h-5 w-5 shrink-0 rounded-[3px] outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  net === null && "border border-dashed border-border",
                  on && "ring-2 ring-foreground/70",
                )}
                style={{ background: heatFill(net, total ? totalScale : scale) }}
              />
            );
          })}
        </span>
      </td>
      <td
        className={cn(
          "tabular py-2 pr-3 text-right font-mono text-xs whitespace-nowrap",
          total && "font-semibold",
          tone(entry.year),
        )}
      >
        {signed(entry.year)}
      </td>
      <td className="tabular py-2 text-right font-mono text-xs whitespace-nowrap text-muted-foreground">
        {money(entry.held)}
      </td>
    </tr>
  );

  return (
    <section aria-labelledby="fpi-sectors-title" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="fpi-sectors-title" className="text-lead font-semibold tracking-[-0.011em]">
          FPI flows by sector
        </h2>
        <p className="tabular text-xs text-muted-foreground">
          NSDL · {fortnightLabel(table.latest.start, table.latest.end)}
        </p>
      </div>

      <div className="panel p-4 sm:p-5">
        <div className="overflow-x-auto" onPointerLeave={() => setActive(null)}>
          <table className="w-full min-w-[48rem] text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="sticky left-0 z-10 bg-card pb-2 text-left font-medium">
                  Sector
                </th>
                <th scope="col" className="pr-3 pb-2 text-right font-medium">
                  Net
                </th>
                <th scope="col" className="pb-2">
                  <span className="sr-only">Net, against the largest</span>
                </th>
                <th scope="col" className="pr-5 pb-2 text-left font-medium">
                  <span className="sr-only">Net by fortnight, last six months</span>
                  <span aria-hidden className="flex gap-0.5">
                    {table.periods.map((period) => (
                      <span key={period.end} className="w-5 shrink-0 whitespace-nowrap">
                        {period.start.endsWith("-01") ? fortnightMonth(period.end) : ""}
                      </span>
                    ))}
                  </span>
                </th>
                <th
                  scope="col"
                  className="pr-3 pb-2 text-right font-medium"
                  title={`Sum of the last ${table.yearSpan} fortnights`}
                >
                  {yearLabel}
                </th>
                <th scope="col" className="pb-2 text-right font-medium">
                  Held
                </th>
              </tr>
            </thead>
            <tbody>{table.sectors.map((entry) => row(entry))}</tbody>
            <tfoot>{row(table.total, true)}</tfoot>
          </table>
        </div>

        <p className="tabular mt-3 border-t border-border/60 pt-3 text-xs" aria-live="polite">
          <span className="font-medium">{shown.row.sector}</span>
          <span className="text-muted-foreground"> · {fortnightLabel(shownPeriod.start, shownPeriod.end)} · </span>
          <span className={cn("font-semibold", tone(shown.row.history[shown.index]))}>
            {signed(shown.row.history[shown.index])}
          </span>
        </p>
      </div>
    </section>
  );
}
