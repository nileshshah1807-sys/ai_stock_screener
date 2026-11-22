"use client";

import Link from "next/link";
import { useState } from "react";

import { DivBar } from "@/components/home/bar";
import { flowFormat } from "@/components/market/flow-format";
import { fortnightLabel, fortnightMonth, gridScale, heatFill, sectorPageSlug } from "@/lib/fpi-flows.mjs";
import { formatDate } from "@/lib/format";
import { marketPath, type Market } from "@/lib/markets";
import { cn } from "@/lib/utils";

type Period = { start: string; end: string };
type SectorRow = { sector: string; net: number | null; held: number | null; history: (number | null)[]; year: number | null };
export type SectorTable = { latest: Period; periods: Period[]; yearSpan: number; sectors: SectorRow[]; total: SectorRow };

/**
 * FPI net equity investment by sector, from NSDL's fortnightly report
 * (lib/fpi-flows.mjs, sectorFlows): the latest fortnight as a diverging bar,
 * the last six months as a row of cells, the year's sum and what FPIs hold.
 * The cell under the pointer or focus gets a tooltip with its figure, so no
 * figure lives only in a colour. Client-side for that tooltip alone.
 */
export function FpiSectorFlows({ market, table, pages }: { market: Market; table: SectorTable; pages: string[] }) {
  const [active, setActive] = useState<{ row: SectorRow; index: number; x: number; y: number } | null>(null);
  // Fixed to the viewport at the cell, so the table's horizontal scroller cannot clip it.
  const point = (row: SectorRow, index: number) => (event: React.SyntheticEvent<HTMLElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    // Kept 110px (half the widest tooltip, plus a gutter) inside the viewport on a phone.
    const x = Math.min(Math.max(box.left + box.width / 2, 110), window.innerWidth - 110);
    setActive({ row, index, x, y: box.top });
  };
  const { money, signed, tone } = flowFormat(market);
  const scale = gridScale(table);
  const barScale = Math.max(1, ...table.sectors.map((s) => Math.abs(s.net ?? 0)));
  // All sectors together run larger than any one: their cells get their own scale.
  const totalScale = Math.max(1, ...table.total.history.map((net) => Math.abs(net ?? 0)));
  const activePeriod = active ? table.periods[active.index] : null;
  const yearLabel = table.yearSpan >= 24 ? "1Y" : `${table.yearSpan} fortnights`;

  const row = (entry: SectorRow, total = false, slug = total ? null : sectorPageSlug(entry.sector, pages)) => (
    <tr key={entry.sector} className={cn("border-t", total ? "border-border" : "border-border/60")}>
      <th
        scope="row"
        className={cn(
          "sticky left-0 z-10 bg-card py-2 pr-3 text-left text-sm whitespace-nowrap",
          total ? "font-semibold" : "font-medium",
        )}
      >
        {slug ? (
          <Link
            href={marketPath(market.slug, `/sectors/${slug}`)}
            className="rounded hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {entry.sector}
          </Link>
        ) : (
          entry.sector
        )}
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
      <td className="py-2 pr-5">
        <div className="w-24">{total ? null : <DivBar value={entry.net} scale={barScale} />}</div>
      </td>
      <td className="w-full py-2 pr-5">
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
                onPointerEnter={point(entry, index)}
                onFocus={point(entry, index)}
                onBlur={() => setActive(null)}
                className={cn(
                  "h-5 min-w-5 flex-1 rounded-[3px] outline-none focus-visible:ring-2 focus-visible:ring-ring",
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
          NSDL fortnightly · as of {formatDate(table.latest.end)}
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
                <th scope="col" className="pr-3 pb-2 text-right font-medium whitespace-nowrap">
                  {fortnightLabel(table.latest.start, table.latest.end).replace(/ \d{4}$/, "")}
                </th>
                <th scope="col" className="pb-2">
                  <span className="sr-only">Net, against the largest</span>
                </th>
                <th scope="col" className="pr-5 pb-2 text-left font-medium">
                  <span className="sr-only">Net by fortnight, last six months</span>
                  <span aria-hidden className="flex gap-0.5">
                    {table.periods.map((period) => (
                      <span key={period.end} className="min-w-5 flex-1 whitespace-nowrap">
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

        {active && activePeriod ? (
          <div
            role="tooltip"
            className="pointer-events-none fixed z-50 -translate-x-1/2 -translate-y-full rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs shadow-md"
            style={{ left: active.x, top: active.y - 6 }}
          >
            <p className="font-medium whitespace-nowrap">{active.row.sector}</p>
            <p className="tabular whitespace-nowrap">
              <span className="text-muted-foreground">{fortnightLabel(activePeriod.start, activePeriod.end)} · </span>
              <span className={cn("font-mono font-semibold", tone(active.row.history[active.index]))}>
                {signed(active.row.history[active.index])}
              </span>
            </p>
          </div>
        ) : null}
      </div>
    </section>
  );
}
