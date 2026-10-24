"use client";

import { Fragment, useState } from "react";
import { ChevronRight, FileText } from "lucide-react";

import { useExpand } from "@/components/motion";
import { StockIdentity } from "@/components/stock-identity";
import { useMarket } from "@/components/market-provider";
import { SegmentedControl } from "@/components/segmented-control";
import { LiveRatio } from "@/components/live-quote";
import { MISSING, formatDateTimeIST } from "@/lib/format";
import type { Market } from "@/lib/markets";
import { amountDigits, formatChange } from "@/lib/results.mjs";
import { cn } from "@/lib/utils";

type Basis = "consolidated" | "standalone";

type Value = number | null;

type MarginRow = { key: string; label: string; values: Value[]; yoy: Value; qoq: Value };

type LineRow = {
  key: string;
  label: string;
  perShare: boolean;
  values: Value[];
  yoy: Value;
  qoq: Value;
  margin: MarginRow | null;
};

export type BasisTable = {
  basis: Basis;
  columns: { period: string; label: string }[];
  rows: LineRow[];
  filedAt: string | null;
  documentUrl: string | null;
};

export type ResultCardData = {
  symbol: string;
  company: string | null;
  bases: BasisTable[];
  marketCap: number | null;
  pe: number | null;
  /** The close the two figures above were worked out at. */
  barDate: string | null;
  /** The company's web domain from the latest run, for its logo. */
  logoDomain: string | null;
};

const BASIS_LABELS: Record<Basis, string> = {
  consolidated: "Consolidated",
  standalone: "Standalone",
};

/** Crore for NSE, as every Indian results table is printed; millions for US. */
function unitFor(market: Market) {
  return market.scale === "indian" ? { divisor: 1e7, label: "Cr" } : { divisor: 1e6, label: "M" };
}

/**
 * A cell's content in a row that opens (MarginRow). A `<tr>` cannot be given
 * a height, so each cell's content is wrapped in a box that can, and the
 * padding moves inside it so the row closes to nothing.
 */
function Opening({ children }: { children: React.ReactNode }) {
  return (
    <div data-expand>
      <div className="py-1.5">{children}</div>
    </div>
  );
}

/** A margin line, grown open under its amount rather than appearing in one frame. */
function MarginRow({ open, children }: { open: boolean; children: React.ReactNode }) {
  const { ref, mounted } = useExpand<HTMLTableRowElement>(open);
  if (!mounted) return null;
  return <tr ref={ref}>{children}</tr>;
}

function ChangeCell({
  value,
  unit = "%",
  opening = false,
}: {
  value: Value;
  unit?: string;
  /** In a MarginRow: the content is wrapped so the row can open. */
  opening?: boolean;
}) {
  const text = formatChange(value, unit) ?? MISSING;
  return (
    <td
      className={cn(
        "tabular whitespace-nowrap px-2 text-right font-mono text-[13px]",
        opening ? "py-0" : "py-2",
        value == null || value === 0
          ? "text-muted-foreground"
          : value > 0
            ? "text-positive"
            : "text-negative",
      )}
    >
      {opening ? <Opening>{text}</Opening> : text}
    </td>
  );
}

/**
 * On a phone a card keeps the changes and this quarter; the quarters they
 * were measured against join from the small breakpoint up, where they fit
 * without scrolling the table sideways.
 */
const OLDER_QUARTER = "hidden sm:table-cell";

function AmountCell({
  text,
  current,
  opening = false,
}: {
  text: string;
  current?: boolean;
  opening?: boolean;
}) {
  return (
    <td
      className={cn(
        "tabular whitespace-nowrap px-2 text-right font-mono text-[13px]",
        opening ? "py-0" : "py-2",
        current ? "font-semibold text-foreground" : cn("text-muted-foreground", OLDER_QUARTER),
      )}
    >
      {opening ? <Opening>{text}</Opening> : text}
    </td>
  );
}

/**
 * One company's quarter: revenue, operating profit, net profit and EPS for
 * the quarter, the one before and the year-ago quarter, with the changes
 * first because they are what a reader scans a season for.
 *
 * A company that files on both bases gets a switch between them; growth is
 * only ever computed within one. Operating and net profit open to their
 * margin, the stock page's OPM and NPM, whose changes are in percentage
 * points -- a growth rate of a margin would read as nonsense.
 */
export function ResultCard({ card }: { card: ResultCardData }) {
  const market = useMarket();
  const [basis, setBasis] = useState<Basis>(card.bases[0]?.basis ?? "consolidated");
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set());
  const table = card.bases.find((entry) => entry.basis === basis) ?? card.bases[0];
  const unit = unitFor(market);

  if (!table) return null;

  const toggle = (key: string) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const amount = (row: LineRow, value: Value, digits: number) => {
    if (value == null) return MISSING;
    if (row.perShare) {
      return value.toLocaleString(market.locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    return (value / unit.divisor).toLocaleString(market.locale, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  };

  return (
    <article className="panel flex min-w-0 flex-col gap-3 p-4">
      <header className="flex items-start justify-between gap-4">
        <StockIdentity
          symbol={card.symbol}
          company={card.company}
          logoDomain={card.logoDomain}
          emphasis="company"
        />
        <span className="tabular shrink-0 pt-0.5 text-right text-xs text-muted-foreground">
          {formatDateTimeIST(table.filedAt)}
        </span>
      </header>

      {card.bases.length > 1 ? (
        <SegmentedControl
          label={`${card.symbol} results basis`}
          value={table.basis}
          onChange={setBasis}
          options={card.bases.map((entry) => ({ value: entry.basis, label: BASIS_LABELS[entry.basis] }))}
        />
      ) : (
        <span className="w-max rounded-md px-3 py-1 text-[0.8125rem] font-medium text-muted-foreground ring-1 ring-inset ring-border">
          {BASIS_LABELS[table.basis]}
        </span>
      )}

      <div className="-mx-1 overflow-x-auto">
        <table className="w-full border-collapse text-sm sm:min-w-[30rem]">
          <caption className="sr-only">
            {card.company ?? card.symbol}, {BASIS_LABELS[table.basis].toLowerCase()} results, amounts in{" "}
            {market.currencySymbol} {unit.label}
          </caption>
          <thead>
            <tr className="whitespace-nowrap border-b text-[11px] text-muted-foreground">
              <th scope="col" className="px-2 py-1.5 text-left font-medium">
                <span className="sr-only">Line</span>
              </th>
              <th scope="col" className="px-2 py-1.5 text-right font-medium">
                YoY
              </th>
              <th scope="col" className="px-2 py-1.5 text-right font-medium">
                QoQ
              </th>
              {table.columns.map((column, index) => (
                <th
                  key={column.period}
                  scope="col"
                  className={cn(
                    "px-2 py-1.5 text-right font-medium",
                    index === 0 ? "text-foreground" : OLDER_QUARTER,
                  )}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y">
            {table.rows.map((row) => {
              const digits = amountDigits(row.values, unit.divisor);
              const expanded = row.margin !== null && open.has(row.key);
              const label = (
                <>
                  {row.label}
                  <span className="ml-1 text-[10px] font-normal text-muted-foreground">
                    {row.perShare ? market.currencySymbol : unit.label}
                  </span>
                </>
              );
              return (
                <Fragment key={row.key}>
                  <tr>
                    <th scope="row" className="px-2 py-2 text-left font-medium">
                      {row.margin ? (
                        <button
                          type="button"
                          onClick={() => toggle(row.key)}
                          aria-expanded={expanded}
                          title={`${expanded ? "Hide" : "Show"} ${row.margin.label}`}
                          className="inline-flex items-center gap-1 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          {label}
                          <ChevronRight
                            className={cn(
                              "size-3.5 text-muted-foreground transition-transform duration-(--duration-fast)",
                              expanded && "rotate-90",
                            )}
                            aria-hidden
                          />
                        </button>
                      ) : (
                        label
                      )}
                    </th>
                    <ChangeCell value={row.yoy} />
                    <ChangeCell value={row.qoq} />
                    {row.values.map((value, index) => (
                      <AmountCell key={index} text={amount(row, value, digits)} current={index === 0} />
                    ))}
                  </tr>
                  {row.margin ? (
                    <MarginRow open={expanded}>
                      <th
                        scope="row"
                        className="py-0 pl-5 pr-2 text-left text-xs font-medium text-muted-foreground"
                      >
                        <Opening>{row.margin.label}</Opening>
                      </th>
                      <ChangeCell value={row.margin.yoy} unit=" pp" opening />
                      <ChangeCell value={row.margin.qoq} unit=" pp" opening />
                      {row.margin.values.map((value, index) => (
                        <AmountCell
                          key={index}
                          text={value == null ? MISSING : `${value.toFixed(1)}%`}
                          current={index === 0}
                          opening
                        />
                      ))}
                    </MarginRow>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      <footer className="mt-auto flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t pt-3 text-xs">
        {table.documentUrl ? (
          <a
            href={table.documentUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <FileText className="size-3.5" aria-hidden />
            Results filing
            <span className="sr-only">(the exchange&rsquo;s document, in a new tab)</span>
          </a>
        ) : (
          <span />
        )}
        <dl className="tabular flex items-center gap-3 text-muted-foreground">
          <div className="flex gap-1">
            <dt>MCap</dt>
            <dd className="font-medium text-foreground">
              <LiveRatio symbol={card.symbol} barDate={card.barDate} metric="market_cap" close={card.marketCap} format="money" />
            </dd>
          </div>
          <div className="flex gap-1 border-l pl-3">
            <dt>P/E</dt>
            <dd className="font-medium text-foreground">
              <LiveRatio symbol={card.symbol} barDate={card.barDate} metric="pe_ratio" close={card.pe} format="positive1" />
            </dd>
          </div>
        </dl>
      </footer>
    </article>
  );
}
