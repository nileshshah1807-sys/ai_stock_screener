"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ArrowLeft } from "lucide-react";

import { IndexOverview } from "@/components/indices/index-overview";
import { KpiBand, PeDistribution } from "@/components/sectors/kpi";
import { MembersMap, MembersTable } from "@/components/sectors/sector-views";
import { formatDate, formatMoneyCompact, formatNumber, formatPercent, formatRatioAsPercent } from "@/lib/format";
import { marketPath, type Market } from "@/lib/markets";
import type { SectorObject } from "@/lib/sector-objects";
import { liveFor } from "@/lib/sectors.mjs";
import { useLiveQuotes } from "@/lib/use-live-quotes";
import { useLiveSectors } from "@/lib/use-live-sectors";
import { cn } from "@/lib/utils";

const pct = (value: number | null) => formatPercent(value, 2, true);
const times = (value: number | null) => (value === null ? "—" : `${formatNumber(value, 1)}×`);

/**
 * One sector: our cap-weighted index of its members with a compare list
 * beside it, what the sector costs (cap-weighted and median), its P/E
 * spread, a heatmap and every member. All of it from one R2 object written
 * by workers/sectors.py; no Supabase read, no rating. During the session
 * the 1D figures (the sector's, its breadth, each member's) are live.
 */
export function SectorView({ market, sector }: { market: Market; sector: SectorObject }) {
  const { summary } = sector;
  const live = liveFor(sector.last_session, useLiveSectors(market.code).get(sector.slug));
  const symbols = useMemo(() => sector.members.map((member) => member.s), [sector.members]);
  const quote = useLiveQuotes(market.code, symbols);
  const members = sector.members.map((member) => {
    const now = liveFor(sector.last_session, quote(member.s));
    return now && now.change_pct !== null ? { ...member, d1: now.change_pct } : member;
  });
  const d1 = live ? live.d1 : sector.d1;
  const breadth = live ?? summary;
  return (
    <div className="space-y-8 px-4 py-5 sm:px-6">
      <div>
        <Link
          href={marketPath(market.slug, "/sectors")}
          className="inline-flex items-center gap-1 rounded-md text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ArrowLeft className="size-3" aria-hidden />
          All sectors
        </Link>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
          <div className="min-w-0">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h1 className="text-title font-semibold">{sector.name}</h1>
              <span className="rounded-md bg-(--control) px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">
                {market.label}
              </span>
            </div>
          </div>
          <div className="sm:text-right">
            <p
              className={cn(
                "numeral text-[1.625rem] font-semibold leading-tight tracking-[-0.02em]",
                d1 === null ? "text-muted-foreground" : d1 >= 0 ? "text-positive" : "text-negative",
              )}
            >
              {pct(d1)}
            </p>
            <p className="text-xs text-muted-foreground">
              {live
                ? `Live · cap-weighted · ${formatDate(live.session)}`
                : `Cap-weighted${sector.last_session ? ` · ${formatDate(sector.last_session)}` : ""}`}
            </p>
          </div>
        </div>
      </div>

      <KpiBand
        items={[
          { label: "1 month", value: pct(sector.m1), tone: sector.m1 },
          { label: "1 year", value: pct(sector.y1), tone: sector.y1 },
          { label: "Total market cap", value: formatMoneyCompact(summary.total_cap, market) },
          {
            label: "Advancing",
            value: `${breadth.advancing} of ${breadth.traded}`,
            share: breadth.traded ? breadth.advancing / breadth.traded : null,
            hint: live ? `Live, ${formatDate(live.session)}` : `In the ${formatDate(sector.run_date)} run`,
          },
        ]}
      />

      {sector.level ? (
        <section aria-labelledby="index-title" className="space-y-3">
          <h2 id="index-title" className="text-lead font-semibold tracking-[-0.011em]">
            Sector index
          </h2>
          <IndexOverview
            market={market}
            name={sector.name}
            row={sector.level}
            live={false}
            members={sector.members.map((member) => ({ symbol: member.s, company: member.c, d1: member.d1 }))}
          />
        </section>
      ) : null}

      <section aria-labelledby="valuation-title" className="space-y-3">
        <h2 id="valuation-title" className="text-lead font-semibold tracking-[-0.011em]">
          Valuation
        </h2>
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
          <ValuationGrid
            items={[
              { label: "Sector P/E", value: times(summary.cap_weighted_pe), hint: "Cap-weighted" },
              { label: "Median P/E", value: times(summary.median_pe), hint: "Of profitable stocks" },
              { label: "Median P/B", value: times(summary.median_pb) },
              { label: "Median ROE", value: formatRatioAsPercent(summary.median_roe, 1) },
              { label: "Median dividend yield", value: formatPercent(summary.median_yield, 2) },
              {
                label: "No positive P/E",
                value: `${summary.no_positive_pe} of ${summary.count}`,
                hint: "Loss-making or not reported",
              },
            ]}
          />
          <PeDistribution buckets={sector.pe_buckets} />
        </div>
      </section>

      <section aria-labelledby="map-title" className="space-y-3">
        <h2 id="map-title" className="text-lead font-semibold tracking-[-0.011em]">
          Heatmap
        </h2>
        <MembersMap market={market} members={members} />
      </section>

      <section aria-labelledby="members-title" className="space-y-3">
        <h2 id="members-title" className="text-lead font-semibold tracking-[-0.011em]">
          All {summary.count.toLocaleString(market.locale)} stocks
        </h2>
        <MembersTable market={market} members={members} />
      </section>
    </div>
  );
}

/** Six figures in a 2x3 (phone) or 3x2 grid, one panel, hairline rules. */
function ValuationGrid({ items }: { items: { label: string; value: string; hint?: string }[] }) {
  return (
    <dl className="panel grid grid-cols-2 gap-px overflow-hidden bg-border sm:grid-cols-3">
      {items.map((item) => (
        <div key={item.label} className="bg-card px-4 py-3">
          <dt className="text-xs text-muted-foreground">{item.label}</dt>
          <dd className="numeral mt-1 text-xl font-semibold leading-tight tracking-[-0.02em]">{item.value}</dd>
          {item.hint ? <p className="mt-1 text-xs text-muted-foreground">{item.hint}</p> : null}
        </div>
      ))}
    </dl>
  );
}
