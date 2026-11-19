import Link from "next/link";
import { ChevronRight, Grid3x3 } from "lucide-react";

import { MembersMap } from "@/components/sectors/sector-views";
import { formatDate, formatNumber, formatPercent } from "@/lib/format";
import { listing } from "@/lib/listing.mjs";
import { marketPath, type Market } from "@/lib/markets";
import type { SectorObject } from "@/lib/sector-objects";
import { peerSlice } from "@/lib/sectors.mjs";
import { cn } from "@/lib/utils";

/** Tiles in the preview: enough to show the sector's shape, few enough to read. */
const PEERS = 24;

const pct = (value: number | null | undefined) => formatPercent(value ?? null, 2, true);
const tone = (value: number | null | undefined) =>
  value === null || value === undefined ? "text-muted-foreground" : value >= 0 ? "text-positive" : "text-negative";
const times = (value: number | null | undefined) =>
  value !== null && value !== undefined && value > 0 ? `${formatNumber(value, 1)}×` : "—";

function ordinal(n: number) {
  const tail = n % 100 >= 11 && n % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${tail}`;
}

/**
 * The stock among its sector, on the stock page: its change beside the
 * sector's own index, its place by size, its P/E beside the sector median,
 * and a small heatmap of the largest members with this one outlined. It is
 * the door to the sector page, which a reader otherwise had no reason to
 * find. From the sector's R2 object (lib/sector-objects.ts); display
 * evidence, no rating.
 */
export function SectorPeers({ market, sector, symbol }: { market: Market; sector: SectorObject; symbol: string }) {
  const { peers, own, capRank, ranked } = peerSlice(sector.members, symbol, PEERS);
  if (!own) return null;
  const ticker = listing(symbol).ticker;
  const href = marketPath(market.slug, `/sectors/${sector.slug}`);

  return (
    <section aria-labelledby="sector-peers-title" className="panel p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h2 id="sector-peers-title" className="text-lead font-semibold tracking-[-0.011em]">
            Among {sector.name}
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {sector.count} stocks{sector.last_session ? ` · closing prices of ${formatDate(sector.last_session)}` : ""}
          </p>
        </div>
        <Link
          prefetch={false}
          href={href}
          className="touch-target inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md bg-(--control) pr-2 pl-2.5 text-xs font-medium text-foreground transition-[background-color] duration-(--duration-fast) ease-(--ease-standard) hover:bg-(--control-hover) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Grid3x3 className="size-3.5" aria-hidden />
          {sector.name} heatmap
          <ChevronRight className="size-3.5 text-muted-foreground" aria-hidden />
        </Link>
      </div>

      <div className="mt-4 grid gap-6 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
        <div className="space-y-4">
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="pb-1.5 text-left font-medium">
                  <span className="sr-only">Series</span>
                </th>
                <th scope="col" className="pb-1.5 text-right font-medium">1D</th>
                <th scope="col" className="pb-1.5 text-right font-medium">1Y</th>
              </tr>
            </thead>
            <tbody className="tabular font-mono text-xs">
              <tr className="border-t border-border/60">
                <th scope="row" className="py-2 text-left font-mono text-sm font-semibold">{ticker}</th>
                <td className={cn("py-2 text-right", tone(own.d1))}>{pct(own.d1)}</td>
                <td className={cn("py-2 text-right", tone(own.y1))}>{pct(own.y1)}</td>
              </tr>
              <tr className="border-t border-border/60">
                <th scope="row" className="py-2 text-left font-sans text-sm font-medium" title="Our market-cap-weighted index of every stock the screener tracks in the sector">
                  Sector index
                </th>
                <td className={cn("py-2 text-right", tone(sector.d1))}>{pct(sector.d1)}</td>
                <td className={cn("py-2 text-right", tone(sector.y1))}>{pct(sector.y1)}</td>
              </tr>
            </tbody>
          </table>

          <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-row bg-border text-sm">
            <div className="bg-muted/40 px-3 py-2.5">
              <dt className="text-[11px] uppercase tracking-wider text-muted-foreground">By size</dt>
              <dd className="tabular mt-0.5 font-semibold">
                {capRank ? `${ordinal(capRank)} of ${ranked}` : "—"}
              </dd>
            </div>
            <div className="bg-muted/40 px-3 py-2.5">
              <dt className="text-[11px] uppercase tracking-wider text-muted-foreground">P/E vs median</dt>
              <dd className="tabular mt-0.5 font-semibold">
                {times(own.pe)}
                <span className="ml-1 text-xs font-normal text-muted-foreground">/ {times(sector.summary.median_pe)}</span>
              </dd>
            </div>
          </dl>
        </div>

        <div className="min-w-0">
          <MembersMap market={market} members={peers} highlight={symbol} preview />
        </div>
      </div>
    </section>
  );
}
