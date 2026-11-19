"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";

import { SymbolText } from "@/components/symbol-text";
import { type ColourOption, type SizeOption, Treemap, type TreemapItem } from "@/components/sectors/treemap";
import { formatMoneyCompact, formatNumber, formatPercent, formatRatioAsPercent } from "@/lib/format";
import { listing } from "@/lib/listing.mjs";
import { marketPath, type Market } from "@/lib/markets";
import type { SectorEntry, SectorMember } from "@/lib/sector-objects";
import { cn } from "@/lib/utils";

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

type Column = {
  key: keyof SectorMember;
  label: string;
  format: (member: SectorMember) => string;
  tone?: boolean;
};

/**
 * Every member, sortable, from the same R2 object as the rest of the page.
 * No rating, rank or score: those stay on the screener for an admin.
 */
export function MembersTable({ market, members }: { market: Market; members: SectorMember[] }) {
  const [sort, setSort] = useState<{ key: keyof SectorMember; dir: 1 | -1 }>({ key: "mc", dir: -1 });
  const [query, setQuery] = useState("");
  const columns: Column[] = [
    { key: "mc", label: "Market cap", format: (m) => formatMoneyCompact(m.mc, market) },
    { key: "d1", label: "1D", format: (m) => pct(m.d1), tone: true },
    { key: "m3", label: "3M", format: (m) => pct(m.m3), tone: true },
    { key: "y1", label: "1Y", format: (m) => pct(m.y1), tone: true },
    { key: "pe", label: "P/E", format: (m) => (m.pe !== null && m.pe > 0 ? formatNumber(m.pe, 1) : "—") },
    { key: "pb", label: "P/B", format: (m) => (m.pb !== null && m.pb > 0 ? formatNumber(m.pb, 1) : "—") },
    { key: "roe", label: "ROE", format: (m) => formatRatioAsPercent(m.roe, 1) },
    { key: "dy", label: "Div yield", format: (m) => formatPercent(m.dy, 2) },
    { key: "rg", label: "Rev growth", format: (m) => formatRatioAsPercent(m.rg, 1, true) },
  ];

  const rows = useMemo(() => {
    const term = query.trim().toLowerCase();
    const shown = term
      ? members.filter((m) => m.s.toLowerCase().includes(term) || (m.c ?? "").toLowerCase().includes(term))
      : members;
    return [...shown].sort((a, b) => {
      const x = a[sort.key];
      const y = b[sort.key];
      // Not reported sorts last either way: it is not the smallest value.
      if (x === null || x === undefined) return y === null || y === undefined ? 0 : 1;
      if (y === null || y === undefined) return -1;
      return typeof x === "number" && typeof y === "number" ? (x - y) * sort.dir : String(x).localeCompare(String(y)) * sort.dir;
    });
  }, [members, sort, query]);

  const header = (key: keyof SectorMember, label: string, align: "left" | "right") => {
    const on = sort.key === key;
    return (
      <th key={key} scope="col" aria-sort={on ? (sort.dir === 1 ? "ascending" : "descending") : "none"} className={cn("px-3 py-2 font-medium", align === "right" ? "text-right" : "text-left")}>
        <button
          type="button"
          onClick={() => setSort({ key, dir: on ? (sort.dir === 1 ? -1 : 1) : key === "s" ? 1 : -1 })}
          className={cn(
            "inline-flex items-center gap-1 rounded hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            on && "text-foreground",
          )}
        >
          {label}
          {on ? (sort.dir === 1 ? <ArrowUp className="size-3" aria-hidden /> : <ArrowDown className="size-3" aria-hidden />) : null}
        </button>
      </th>
    );
  };

  return (
    <div className="space-y-3">
      <label className="block w-full sm:w-64">
        <span className="sr-only">Search members</span>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search ticker or name…"
          className="h-8 w-full rounded-md bg-(--control) px-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      </label>
      <div className="panel overflow-x-auto">
        <table className="w-full min-w-[56rem] text-sm">
          <thead className="border-b border-border text-xs text-muted-foreground">
            <tr>
              {header("s", "Company", "left")}
              {columns.map((column) => header(column.key, column.label, "right"))}
            </tr>
          </thead>
          <tbody>
            {rows.map((member) => (
              <tr key={member.s} className="border-b border-border/60 last:border-0 hover:bg-(--control)">
                <th scope="row" className="max-w-[18rem] px-3 py-2 text-left font-normal">
                  <Link
                    prefetch={false}
                    href={stockHref(market, member.s)}
                    className="block rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="block font-mono text-xs font-semibold">
                      <SymbolText symbol={member.s} />
                    </span>
                    {member.c ? <span className="block truncate text-xs text-muted-foreground">{member.c}</span> : null}
                  </Link>
                </th>
                {columns.map((column) => {
                  const value = member[column.key] as number | null;
                  return (
                    <td
                      key={column.key}
                      className={cn(
                        "tabular px-3 py-2 text-right font-mono text-xs",
                        column.tone && value !== null && (value >= 0 ? "text-positive" : "text-negative"),
                        value === null && "text-muted-foreground",
                      )}
                    >
                      {column.format(member)}
                    </td>
                  );
                })}
              </tr>
            ))}
            {!rows.length ? (
              <tr>
                <td colSpan={columns.length + 1} className="px-3 py-10 text-center text-sm text-muted-foreground">
                  No member matches “{query}”. Search by ticker or company name.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
