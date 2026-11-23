"use client";

import { type ColourOption, type SizeOption, Treemap, type TreemapItem } from "@/components/sectors/treemap";
import { formatMoneyCompact, formatNumber, formatPercent, formatRatioAsPercent } from "@/lib/format";
import { listing } from "@/lib/listing.mjs";
import { marketPath, type Market } from "@/lib/markets";
import type { SectorEntry, SectorMember } from "@/lib/sector-objects";

const pct = (value: number | null) => formatPercent(value, 2, true);
const times = (value: number | null) => (value === null ? "—" : `${formatNumber(value, 1)}×`);

const stockHref = (market: Market, symbol: string) => marketPath(market.slug, `/stocks/${encodeURIComponent(symbol)}`);

/** Every sector as a tile: area is its market cap, colour its level's change. */
export function SectorsMap({ market, sectors }: { market: Market; sectors: SectorEntry[] }) {
  const money = (value: number | null) => formatMoneyCompact(value, market);
  const items: TreemapItem[] = sectors.map((sector) => ({
    key: sector.slug,
    label: sector.name,
    title: `${sector.name} (${sector.count} stocks)`,
    href: marketPath(market.slug, `/sectors/${sector.slug}`),
    values: { cap: sector.total_cap, count: sector.count, d1: sector.d1, m1: sector.m1, y1: sector.y1 },
  }));
  const sizes: SizeOption[] = [
    { value: "cap", label: "Market cap", field: "cap", format: money },
    { value: "count", label: "Stocks", field: "count", format: (v) => formatNumber(v, 0) },
  ];
  const colours: ColourOption[] = [
    { value: "d1", label: "1D", field: "d1", kind: "diverging", scales: [1, 2, 3], format: pct },
    { value: "m1", label: "1M", field: "m1", kind: "diverging", scales: [3, 5, 10], format: pct },
    { value: "y1", label: "1Y", field: "y1", kind: "diverging", scales: [10, 20, 40], format: pct },
  ];
  return (
    <Treemap
      items={items}
      sizes={sizes}
      colours={colours}
      label="Sectors heatmap"
      height={380}
    />
  );
}

/**
 * One sector's members as tiles, with StocksSena's size and colour choices
 * where we hold the field. `highlight` outlines one member; `preview` drops
 * the pickers for a smaller map that links on to the sector page.
 */
export function MembersMap({
  market,
  members,
  highlight,
  preview = false,
}: {
  market: Market;
  members: SectorMember[];
  highlight?: string;
  preview?: boolean;
}) {
  const money = (value: number | null) => formatMoneyCompact(value, market);
  const items: TreemapItem[] = members.map((member) => ({
    key: member.s,
    label: listing(member.s).ticker,
    title: member.c ? `${listing(member.s).ticker} · ${member.c}` : listing(member.s).ticker,
    href: stockHref(market, member.s),
    values: {
      mc: member.mc,
      tv: member.tv,
      d1: member.d1,
      m3: member.m3,
      y1: member.y1,
      roe: member.roe,
      rg: member.rg,
      pe: member.pe !== null && member.pe > 0 ? member.pe : null,
      pb: member.pb !== null && member.pb > 0 ? member.pb : null,
    },
  }));
  const sizes: SizeOption[] = [
    { value: "mc", label: "Market cap", field: "mc", format: money },
    { value: "tv", label: "Traded value", field: "tv", format: money },
    { value: "equal", label: "Equal", field: null, format: () => "" },
  ];
  const colours: ColourOption[] = [
    { value: "d1", label: "1D", field: "d1", kind: "diverging", scales: [1, 3, 5], format: pct },
    { value: "m3", label: "3M", field: "m3", kind: "diverging", scales: [5, 15, 30], format: pct },
    { value: "y1", label: "1Y", field: "y1", kind: "diverging", scales: [10, 30, 60], format: pct },
    { value: "roe", label: "ROE", field: "roe", kind: "rank", format: (v) => formatRatioAsPercent(v, 1) },
    { value: "rg", label: "Rev growth", field: "rg", kind: "rank", format: (v) => formatRatioAsPercent(v, 1, true) },
    { value: "pe", label: "P/E", field: "pe", kind: "rank", format: times },
    { value: "pb", label: "P/B", field: "pb", kind: "rank", format: times },
  ];
  return (
    <Treemap
      items={items}
      sizes={sizes}
      colours={colours}
      label="Members heatmap"
      highlight={highlight}
      controls={!preview}
      height={preview ? 220 : undefined}
    />
  );
}
