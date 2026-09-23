"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";

import { cn } from "@/lib/utils";
import { GlassTrack } from "@/components/glass-track";
import { formatDate, MISSING } from "@/lib/format";
import { availableViews, buildView, periodLabel, VIEWS } from "@/lib/financials.mjs";
import type { Market } from "@/lib/markets";
import type { FinancialStatementsRow } from "@/lib/queries";

type ViewKey = keyof typeof VIEWS;

type Column = { period: string; label: string; source: number | null };

type Row = {
  id: string;
  type: "value" | "growth" | "ratio";
  label: string;
  emphasis?: boolean;
  perShare?: boolean;
  asMultiple?: boolean;
  cells: (number | null)[];
};

/** Past this, the source's latest quarter is behind what companies have filed. */
const STALE_QUARTER_DAYS = 135;

/**
 * Statement amounts in the unit a reader of that market expects: crore for
 * NSE (how every Indian results table is printed), millions for US.
 */
function unitFor(market: Market) {
  return market.scale === "indian"
    ? { divisor: 1e7, label: `${market.currencySymbol} Cr` }
    : { divisor: 1e6, label: `${market.currencySymbol} M` };
}

/**
 * Decimals for a whole row, from its largest figure. Small companies report
 * single-digit crore amounts, and rounding those to whole numbers would erase
 * the quarter-to-quarter movement -- but deciding per cell would print "42.0"
 * in a column of "1,568"s, so the row's scale decides for every cell in it.
 */
function amountDigits(row: Row, divisor: number) {
  const largest = Math.max(0, ...row.cells.map((v) => (v == null ? 0 : Math.abs(v / divisor))));
  if (largest >= 100) return 0;
  return largest >= 10 ? 1 : 2;
}

function formatCell(
  row: Row,
  value: number | null,
  market: Market,
  divisor: number,
  digits: number,
) {
  if (value == null) return MISSING;
  if (row.type === "growth") {
    // The sign is always written, so direction never depends on colour alone.
    const sign = value > 0 ? "+" : value < 0 ? "-" : "";
    return `${sign}${Math.abs(value).toFixed(1)}%`;
  }
  if (row.type === "ratio") {
    return row.asMultiple ? `${value.toFixed(2)}×` : `${value.toFixed(1)}%`;
  }
  if (row.perShare) {
    return value.toLocaleString(market.locale, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }
  return (value / divisor).toLocaleString(market.locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function growthTone(row: Row, value: number | null) {
  if (row.type !== "growth" || value == null || value === 0) return "";
  return value > 0 ? "text-positive" : "text-negative";
}

export function Financials({
  data,
  market,
  symbol,
  asOf,
}: {
  data: FinancialStatementsRow | null;
  market: Market;
  symbol: string;
  /** The run's price-bar date: staleness is judged against the data, not the viewer's clock. */
  asOf: string | null;
}) {
  const views = useMemo(
    () => (data?.has_data ? (availableViews(data.statements) as ViewKey[]) : []),
    [data],
  );
  const [view, setView] = useState<ViewKey | null>(views[0] ?? null);
  const current = view && views.includes(view) ? view : (views[0] ?? null);

  if (!data || !data.has_data || !current) {
    return (
      <div className="rounded-row border border-dashed border-border px-5 py-10 text-center">
        <p className="text-sm font-medium">
          {data
            ? `The source reports no financial statements for ${symbol}.`
            : `Financial statements for ${symbol} have not been collected yet.`}
        </p>
        <p className="mx-auto mt-1 max-w-md text-xs text-muted-foreground">
          {data
            ? `Checked ${formatDate(data.fetched_at)}. Newly listed companies often have no history at the source until their first results are filed.`
            : "They are refreshed in the background once a day, most-investable names first."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="max-w-full overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <GlassTrack label="Statement" role="tablist" className="w-max gap-0.5 p-1">
            {views.map((key) => {
              const selected = key === current;
              return (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  onPointerDown={(event) => {
                    if (event.button === 0) setView(key);
                  }}
                  onClick={() => setView(key)}
                  className={cn(
                    "inline-flex min-h-8 items-center whitespace-nowrap rounded-full px-3 text-[0.8125rem] sm:px-4",
                    "transition-[color,transform] duration-(--duration-spring-bouncy) ease-(--ease-spring)",
                    "active:scale-[0.95] active:duration-(--duration-press) active:ease-out",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    selected
                      ? "font-semibold text-foreground"
                      : "font-medium text-muted-foreground hover:text-foreground",
                  )}
                >
                  <span className="sm:hidden">{VIEWS[key].short}</span>
                  <span className="hidden sm:inline">{VIEWS[key].label}</span>
                </button>
              );
            })}
          </GlassTrack>
        </div>
        <span className="rounded-full bg-(--control) px-3 py-1 text-xs font-medium text-muted-foreground">
          {unitFor(market).label}
          {current === "quarterly" || current === "profit_loss" ? " · EPS in " + market.currencySymbol : ""}
        </span>
      </div>

      <StatementTable key={current} data={data} view={current} market={market} asOf={asOf} />

      <p className="text-xs leading-relaxed text-muted-foreground">
        As reported by {data.source}, fetched {formatDate(data.fetched_at)}.
        Growth compares each period with the one exactly a quarter or a year
        earlier; it is blank when that period was not reported or its base was
        zero or a loss. Operating profit is EBITDA.
      </p>
    </div>
  );
}

function StatementTable({
  data,
  view,
  market,
  asOf,
}: {
  data: FinancialStatementsRow;
  view: ViewKey;
  market: Market;
  asOf: string | null;
}) {
  const table = useMemo(
    () => buildView(data.statements, view) as { columns: Column[]; rows: Row[] },
    [data, view],
  );
  const { divisor } = unitFor(market);
  const scroller = useRef<HTMLDivElement>(null);

  // Latest period on the right, like every results table -- so start scrolled
  // there. On a phone the older quarters are a swipe left, not the default.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [table]);

  const columns = table.columns;
  const rows = table.rows;
  const latest = columns.length - 1;
  const lastReported = columns[latest]?.period;
  const stale =
    view === "quarterly" &&
    Boolean(lastReported && asOf) &&
    (Date.parse(asOf!) - Date.parse(lastReported)) / 86_400_000 > STALE_QUARTER_DAYS;

  // Headline for the latest quarter: the three figures a results table is
  // read for, pulled out so they do not have to be found in the grid.
  const headline =
    view === "quarterly"
      ? ["Revenue YoY", "Net profit YoY", "OPM"]
          .map((label) => rows.find((row) => row.label === label))
          .filter((row): row is Row => Boolean(row) && row!.cells[latest] != null)
      : [];

  return (
    <div className="space-y-3">
      {stale ? (
        <p className="flex items-start gap-2 rounded-row border border-caution/30 bg-caution/8 px-3 py-2 text-xs text-caution">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          The latest quarter the source has for this company is{" "}
          {periodLabel(lastReported)}. Newer results may have been filed.
        </p>
      ) : null}

      {headline.length ? (
        <section aria-label={`Latest quarter, ${columns[latest].label}`}>
          <p className="mb-1.5 text-xs text-muted-foreground">
            Latest quarter · <span className="font-medium text-foreground">{columns[latest].label}</span>
          </p>
          <dl className="grid grid-cols-3 gap-px overflow-hidden rounded-row bg-border">
            {headline.map((row) => (
              <div key={row.id} className="bg-muted/40 px-3 py-3 sm:px-4">
                <dt className="text-[11px] uppercase tracking-wider text-muted-foreground">
                  {row.label}
                </dt>
                <dd className={cn("tabular mt-0.5 text-lead font-semibold", growthTone(row, row.cells[latest]))}>
                  {formatCell(row, row.cells[latest], market, divisor, 0)}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      <div
        ref={scroller}
        className="overflow-x-auto rounded-row border border-(--panel-edge)"
      >
        <table className="w-full min-w-max border-separate border-spacing-0 text-sm">
          <caption className="sr-only">
            {VIEWS[view].label}, {unitFor(market).label}
          </caption>
          <thead>
            <tr>
              <th
                scope="col"
                className="sticky left-0 z-10 min-w-[11rem] border-b border-border bg-[color-mix(in_oklab,var(--muted)_55%,var(--card))] px-4 py-2.5 text-left text-xs font-medium text-muted-foreground"
              >
                {view === "quarterly" ? "Quarter ended" : "Year ended"}
              </th>
              {columns.map((column, index) => (
                <th
                  key={column.period}
                  scope="col"
                  title={column.source == null ? "Not reported by the source" : undefined}
                  className={cn(
                    "border-b border-border bg-[color-mix(in_oklab,var(--muted)_55%,var(--card))] px-4 py-2.5 text-right text-xs whitespace-nowrap",
                    column.source == null
                      ? "font-normal text-muted-foreground/60 italic"
                      : index === latest
                        ? "font-semibold text-foreground"
                        : "font-medium text-muted-foreground",
                  )}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const derived = row.type !== "value";
              const digits = amountDigits(row, divisor);
              return (
                <tr key={row.id} className="group">
                  <th
                    scope="row"
                    className={cn(
                      "sticky left-0 z-10 border-b border-border/60 bg-card px-4 text-left whitespace-nowrap transition-colors group-hover:bg-[color-mix(in_oklab,var(--muted)_40%,var(--card))]",
                      derived
                        ? "py-1.5 pl-7 text-xs font-normal text-muted-foreground"
                        : cn("py-2.5", row.emphasis ? "font-semibold" : "font-medium"),
                    )}
                  >
                    {row.label}
                  </th>
                  {row.cells.map((value, index) => {
                    const gap = columns[index].source == null;
                    return (
                      <td
                        key={columns[index].period}
                        className={cn(
                          "tabular border-b border-border/60 px-4 text-right whitespace-nowrap transition-colors group-hover:bg-[color-mix(in_oklab,var(--muted)_40%,var(--card))]",
                          derived ? "py-1.5 text-xs" : "py-2.5",
                          row.emphasis && !derived && "font-semibold",
                          gap && "bg-muted/30",
                          value == null
                            ? "text-muted-foreground/50"
                            : growthTone(row, value) || (derived ? "text-muted-foreground" : ""),
                        )}
                      >
                        {formatCell(row, value, market, divisor, digits)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
