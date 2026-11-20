"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ChevronRight, Grid3x3 } from "lucide-react";

import { MembersMap } from "@/components/sectors/sector-views";
import { formatDate, formatNumber, formatPercent } from "@/lib/format";
import { listing } from "@/lib/listing.mjs";
import { marketPath, type Market } from "@/lib/markets";
import type { SectorMember, SectorObject } from "@/lib/sector-objects";
import { liveFor, withLiveChange } from "@/lib/sectors.mjs";
import { useLiveQuotes } from "@/lib/use-live-quotes";
import { useLiveSectors } from "@/lib/use-live-sectors";
import { cn } from "@/lib/utils";

/** The sector's figures the panel shows; the members stay on the server. */
export type PeerSector = Pick<SectorObject, "name" | "slug" | "count" | "last_session" | "d1" | "y1"> & {
  median_pe: number | null;
};

export type PeerSlice = { peers: SectorMember[]; own: SectorMember; capRank: number | null; ranked: number };

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
 * The body of SectorPeers (./sector-peers.tsx), in the browser so that
 * during the session the 1D figures are live, as on the sector page.
 */
export function SectorPeersPanel({
  market,
  sector,
  slice,
  symbol,
}: {
  market: Market;
  sector: PeerSector;
  slice: PeerSlice;
  symbol: string;
}) {
  const symbols = useMemo(() => slice.peers.map((member) => member.s), [slice.peers]);
  const quote = useLiveQuotes(market.code, symbols);
  const liveSector = liveFor(sector.last_session, useLiveSectors(market.code).get(sector.slug));
  const { own: closeOwn, capRank, ranked } = slice;
  const peers = withLiveChange(slice.peers, sector.last_session, quote);
  const own = peers.find((member) => member.s === symbol) ?? closeOwn;
  const sectorD1 = liveSector ? liveSector.d1 : sector.d1;
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
            {sector.count} stocks{sector.last_session ? ` · ${formatDate(sector.last_session)}` : ""}
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
                <td className={cn("py-2 text-right", tone(sectorD1))}>{pct(sectorD1)}</td>
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
                <span className="ml-1 text-xs font-normal text-muted-foreground">/ {times(sector.median_pe)}</span>
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
