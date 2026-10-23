"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { SegmentedControl } from "@/components/segmented-control";
import { formatDate, MISSING } from "@/lib/format";
import { buildHolders, buildPattern } from "@/lib/shareholding.mjs";
import type { Market } from "@/lib/markets";
import type { BulkBlockDealRow, Shareholding as ShareholdingData } from "@/lib/queries";

type Column = { period: string; label: string };
type TableRow = {
  key: string;
  label: string;
  percent?: boolean;
  cells: (number | null)[];
  qoq?: number | null;
  yoy?: number | null;
  group?: string;
  lowerIsBetter?: boolean;
};

type View = "pattern" | "deals";
type Breakdown = "promoter" | "others";

const GROUP_LABEL: Record<string, string> = { fii: "FII", dii: "DII", public: "Public" };

const HEAD = "border-b border-border bg-[color-mix(in_oklab,var(--muted)_55%,var(--card))] px-4 py-2.5 text-xs whitespace-nowrap";
const CELL = "tabular border-b border-border/60 px-4 py-2.5 text-right whitespace-nowrap transition-colors group-hover:bg-[color-mix(in_oklab,var(--muted)_40%,var(--card))]";
const ROW_HEAD = "sticky left-0 z-10 border-b border-border/60 bg-card px-4 py-2.5 text-left font-medium transition-colors group-hover:bg-[color-mix(in_oklab,var(--muted)_40%,var(--card))]";

function formatValue(value: number | null | undefined, percent: boolean, locale: string) {
  if (value == null) return MISSING;
  return value.toLocaleString(locale, percent
    ? { minimumFractionDigits: 2, maximumFractionDigits: 2 }
    : { maximumFractionDigits: 0 });
}

function formatChange(value: number | null | undefined, percent: boolean, locale: string) {
  if (value == null) return MISSING;
  // The sign is always written, so direction never depends on colour alone.
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${formatValue(Math.abs(value), percent, locale)}`;
}

// A falling public stake or shareholder count is the good direction, so those rows flip.
function changeTone(value: number | null | undefined, lowerIsBetter?: boolean) {
  if (!value) return "text-muted-foreground";
  return value > 0 !== !lowerIsBetter ? "text-negative" : "text-positive";
}

function QuarterTable({
  caption,
  corner,
  columns,
  rows,
  market,
  changes,
}: {
  caption: string;
  corner: string;
  columns: Column[];
  rows: TableRow[];
  market: Market;
  changes: boolean;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  // Latest quarter on the right, so start scrolled there, as Financials does.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [columns]);
  const latest = columns.length - 1;

  return (
    <div ref={scroller} className="overflow-x-auto rounded-row border border-(--panel-edge)">
      <table className="w-full min-w-max border-separate border-spacing-0 text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col" className={cn(HEAD, "sticky left-0 z-10 min-w-[11rem] text-left font-medium text-muted-foreground")}>
              {corner}
            </th>
            {columns.map((column, index) => (
              <th
                key={column.period}
                scope="col"
                className={cn(HEAD, "text-right", index === latest ? "font-semibold text-foreground" : "font-medium text-muted-foreground")}
              >
                {column.label}
              </th>
            ))}
            {changes ? (
              <>
                <th scope="col" title="Change over the last quarter, in percentage points" className={cn(HEAD, "text-right font-medium text-muted-foreground")}>QoQ</th>
                <th scope="col" title="Change over the last year, in percentage points" className={cn(HEAD, "text-right font-medium text-muted-foreground")}>YoY</th>
              </>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const percent = row.percent ?? true;
            return (
              <tr key={row.key} className="group">
                <th scope="row" className={ROW_HEAD}>
                  <span className="whitespace-nowrap">{row.label}</span>
                  {row.group ? (
                    <span className="ml-2 rounded-md bg-(--control) px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                      {GROUP_LABEL[row.group]}
                    </span>
                  ) : null}
                </th>
                {row.cells.map((value, index) => (
                  <td key={columns[index].period} className={cn(CELL, value == null && "text-muted-foreground/50")}>
                    {formatValue(value, percent, market.locale)}
                  </td>
                ))}
                {changes ? (
                  <>
                    <td className={cn(CELL, "text-xs", changeTone(row.qoq, row.lowerIsBetter))}>{formatChange(row.qoq, percent, market.locale)}</td>
                    <td className={cn(CELL, "text-xs", changeTone(row.yoy, row.lowerIsBetter))}>{formatChange(row.yoy, percent, market.locale)}</td>
                  </>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function DealsTable({ deals, market }: { deals: BulkBlockDealRow[]; market: Market }) {
  if (!deals.length) {
    return (
      <p className="rounded-row border border-dashed border-border px-5 py-8 text-center text-sm text-muted-foreground">
        No bulk or block deals on record.
      </p>
    );
  }
  const number = (value: number, digits: number) =>
    value.toLocaleString(market.locale, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return (
    <div className="overflow-x-auto rounded-row border border-(--panel-edge)">
      <table className="w-full min-w-max border-separate border-spacing-0 text-sm">
        <caption className="sr-only">Bulk and block deals, newest first</caption>
        <thead>
          <tr>
            {["Date", "Deal", "Client", "Side", "Quantity", `Price (${market.currencySymbol})`, `Value (${market.currencySymbol} Cr)`].map(
              (label, index) => (
                <th key={label} scope="col" className={cn(HEAD, "font-medium text-muted-foreground", index >= 4 ? "text-right" : "text-left")}>
                  {label}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {deals.map((deal, index) => (
            <tr key={`${deal.deal_date}-${deal.kind}-${deal.client_name}-${index}`} className="group">
              <td className={cn(CELL, "text-left")}>{formatDate(deal.deal_date)}</td>
              <td className={cn(CELL, "text-left capitalize")}>{deal.kind}</td>
              <td className={cn(CELL, "max-w-[22rem] truncate text-left")} title={deal.client_name}>
                {deal.client_name}
              </td>
              <td className={cn(CELL, "text-left font-medium", deal.side === "BUY" ? "text-positive" : "text-negative")}>
                {deal.side === "BUY" ? "Buy" : "Sell"}
              </td>
              <td className={CELL}>{number(deal.quantity, 0)}</td>
              <td className={CELL}>{number(deal.price, 2)}</td>
              <td className={CELL}>{number((deal.quantity * deal.price) / 1e7, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Shareholding({
  data,
  market,
  symbol,
}: {
  data: ShareholdingData | null;
  market: Market;
  symbol: string;
}) {
  const [view, setView] = useState<View>("pattern");
  const [breakdown, setBreakdown] = useState<Breakdown>("promoter");
  const patterns = useMemo(() => data?.patterns ?? [], [data]);
  const pattern = useMemo(() => buildPattern(patterns) as { columns: Column[]; rows: TableRow[] }, [patterns]);
  const holders = useMemo(() => {
    const table = buildHolders(patterns, breakdown === "promoter" ? ["promoter"] : ["fii", "dii", "public"]) as {
      columns: Column[];
      rows: { key: string; name: string; group: string; cells: (number | null)[] }[];
    };
    return {
      columns: table.columns,
      rows: table.rows.map((row) => ({
        key: row.key,
        label: row.name,
        cells: row.cells,
        group: breakdown === "promoter" ? undefined : row.group,
      })),
    };
  }, [patterns, breakdown]);

  if (!patterns.length && !data?.deals.length) {
    return (
      <div className="rounded-row border border-dashed border-border px-5 py-10 text-center">
        <p className="text-sm font-medium">No shareholding filings for {symbol} have been stored yet.</p>
        <p className="mx-auto mt-1 max-w-md text-xs text-muted-foreground">
          Patterns are read from NSE as companies file them, within 21 days of each quarter end.
        </p>
      </div>
    );
  }

  const latest = [...patterns].sort((a, b) => b.period_end.localeCompare(a.period_end))[0];

  return (
    <div className="space-y-4">
      <SegmentedControl<View>
        label="Shareholding view"
        value={view}
        onChange={setView}
        options={[
          { value: "pattern", label: "Shareholding pattern" },
          { value: "deals", label: "Bulk & block deals" },
        ]}
      />

      {view === "pattern" ? (
        patterns.length ? (
          <>
            <QuarterTable
              caption="Shareholding pattern by quarter, percent of shares"
              corner="Stake"
              columns={pattern.columns}
              rows={pattern.rows}
              market={market}
              changes
            />

            <SegmentedControl<Breakdown>
              label="Holder breakdown"
              value={breakdown}
              onChange={setBreakdown}
              options={[
                { value: "promoter", label: "Promoter breakdown" },
                { value: "others", label: "FII / DII / Public breakdown" },
              ]}
            />

            {holders.rows.length ? (
              <QuarterTable
                caption={`${breakdown === "promoter" ? "Promoter" : "FII, DII and public"} holders by quarter, percent of shares`}
                corner={breakdown === "promoter" ? "Promoter %" : "Holder %"}
                columns={holders.columns}
                rows={holders.rows}
                market={market}
                changes={false}
              />
            ) : (
              <p className="rounded-row border border-dashed border-border px-5 py-8 text-center text-sm text-muted-foreground">
                {breakdown === "promoter" ? "No promoter group is on record." : "No holder of 1% or more is named."}
              </p>
            )}

            <p className="text-xs leading-relaxed text-muted-foreground">
              As filed with NSE; latest filing {formatDate(latest.filed_at)} (
              <a href={latest.document_url} target="_blank" rel="noreferrer" className="underline underline-offset-2">
                XBRL
              </a>
              ). FII is foreign institutions and DII domestic institutions; public is everyone
              else, employee trusts and the government included. QoQ and YoY are changes in
              percentage points. Public holders are named only from 1%.
            </p>
          </>
        ) : (
          <p className="rounded-row border border-dashed border-border px-5 py-8 text-center text-sm text-muted-foreground">
            No shareholding filings stored yet.
          </p>
        )
      ) : (
        <>
          <DealsTable deals={data?.deals ?? []} market={market} />
          <p className="text-xs leading-relaxed text-muted-foreground">
            As listed by NSE. A bulk deal is a trade of more than 0.5% of a company&apos;s shares in
            one session; a block deal a single large trade in the exchange&apos;s separate block
            window. The latest 200 are shown.
          </p>
        </>
      )}
    </div>
  );
}
