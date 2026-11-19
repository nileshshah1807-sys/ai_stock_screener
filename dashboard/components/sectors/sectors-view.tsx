"use client";

import Link from "next/link";

import { KpiBand } from "@/components/sectors/kpi";
import { SectorsMap } from "@/components/sectors/sector-views";
import { formatDate, formatMoneyCompact, formatPercent } from "@/lib/format";
import { marketPath, type Market } from "@/lib/markets";
import type { SectorEntry } from "@/lib/sector-objects";
import { liveFor } from "@/lib/sectors.mjs";
import { useLiveSectors } from "@/lib/use-live-sectors";
import { cn } from "@/lib/utils";

const pct = (value: number | null) => formatPercent(value, 2, true);

/** The page's body, given the directory's sectors (empty before the first publish). */
export function SectorsView({ market, sectors: closed }: { market: Market; sectors: SectorEntry[] }) {
  const live = useLiveSectors(closed.length ? market.code : null);
  // During the session each sector's 1D and breadth are the live ones; its 1M and 1Y stay at the close.
  const nows = closed.map((sector) => liveFor(sector.last_session, live.get(sector.slug)));
  const liveSession = nows.find(Boolean)?.session ?? null;
  const sectors = closed.map((sector, index) => {
    const now = nows[index];
    return now ? { ...sector, d1: now.d1, advancing: now.advancing, declining: now.declining, traded: now.traded } : sector;
  });
  const asOf = sectors.map((sector) => sector.last_session).filter(Boolean).sort().at(-1) ?? null;

  if (!sectors.length) {
    return (
      <div className="space-y-6 px-4 py-5 sm:px-6">
        <Heading count={0} market={market.label} asOf={null} />
        <div className="panel px-5 py-12 text-center">
          <p className="text-sm font-medium">Sector pages are not published for {market.label} yet.</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
            They are built each evening with the market breadth charts. Check back after the next run.
          </p>
        </div>
      </div>
    );
  }

  const ranked = sectors.filter((sector) => sector.d1 !== null).sort((a, b) => b.d1! - a.d1!);
  const up = ranked.filter((sector) => sector.d1! > 0).length;
  const advancing = sectors.reduce((sum, sector) => sum + sector.advancing, 0);
  const traded = sectors.reduce((sum, sector) => sum + sector.traded, 0);
  const leader = ranked[0];
  const laggard = ranked.at(-1);

  return (
    <div className="space-y-8 px-4 py-5 sm:px-6">
      <Heading count={sectors.length} market={market.label} asOf={asOf} liveSession={liveSession} />

      <KpiBand
        items={[
          { label: "Sectors up", value: `${up} of ${ranked.length}`, share: ranked.length ? up / ranked.length : null },
          {
            label: "Stocks advancing",
            value: `${advancing.toLocaleString(market.locale)} of ${traded.toLocaleString(market.locale)}`,
            share: traded ? advancing / traded : null,
          },
          ...(leader ? [{ label: "Leading", value: pct(leader.d1), tone: leader.d1, hint: leader.name }] : []),
          ...(laggard && laggard !== leader
            ? [{ label: "Lagging", value: pct(laggard.d1), tone: laggard.d1, hint: laggard.name }]
            : []),
        ]}
      />

      <section aria-labelledby="map-title" className="space-y-3">
        <h2 id="map-title" className="text-lead font-semibold tracking-[-0.011em]">
          Heatmap
        </h2>
        <SectorsMap market={market} sectors={sectors} />
      </section>

      <section aria-labelledby="all-title" className="space-y-3">
        <h2 id="all-title" className="text-lead font-semibold tracking-[-0.011em]">
          All sectors
        </h2>
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[44rem] text-sm">
            <thead className="border-b border-border text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-medium">Sector</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Stocks</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Market cap</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">1D</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">1M</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">1Y</th>
                <th scope="col" className="px-3 py-2 text-left font-medium">Advancing</th>
              </tr>
            </thead>
            <tbody>
              {[...sectors]
                .sort((a, b) => (b.total_cap ?? 0) - (a.total_cap ?? 0))
                .map((sector) => (
                  <SectorRow
                    key={sector.slug}
                    sector={sector}
                    href={marketPath(market.slug, `/sectors/${sector.slug}`)}
                    money={formatMoneyCompact(sector.total_cap, market)}
                  />
                ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function Heading({
  count,
  market,
  asOf,
  liveSession = null,
}: {
  count: number;
  market: string;
  asOf: string | null;
  liveSession?: string | null;
}) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <h1 className="text-title font-semibold">Sectors</h1>
      {asOf ? (
        <p className="tabular text-xs text-muted-foreground">
          {count} {market} sectors · {liveSession ? `Live · ${formatDate(liveSession)}` : formatDate(asOf)}
        </p>
      ) : null}
    </div>
  );
}

function Change({ value }: { value: number | null }) {
  return (
    <td
      className={cn(
        "tabular px-3 py-2 text-right font-mono text-xs",
        value === null ? "text-muted-foreground" : value >= 0 ? "text-positive" : "text-negative",
      )}
    >
      {pct(value)}
    </td>
  );
}

function SectorRow({ sector, href, money }: { sector: SectorEntry; href: string; money: string }) {
  const share = sector.traded ? sector.advancing / sector.traded : 0;
  return (
    <tr className="border-b border-border/60 last:border-0 hover:bg-(--control)">
      <th scope="row" className="px-3 py-2 text-left font-medium">
        <Link
          prefetch={false}
          href={href}
          className="rounded hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {sector.name}
        </Link>
      </th>
      <td className="tabular px-3 py-2 text-right font-mono text-xs">{sector.count}</td>
      <td className="tabular px-3 py-2 text-right font-mono text-xs">{money}</td>
      <Change value={sector.d1} />
      <Change value={sector.m1} />
      <Change value={sector.y1} />
      <td className="px-3 py-2">
        <span className="flex items-center gap-2">
          <span className="tabular w-16 font-mono text-xs">
            {sector.advancing}/{sector.traded}
          </span>
          <span className="h-1 w-20 overflow-hidden rounded-full bg-(--control)" aria-hidden>
            <span className="block h-full rounded-full bg-positive" style={{ width: `${Math.round(share * 100)}%` }} />
          </span>
        </span>
      </td>
    </tr>
  );
}
