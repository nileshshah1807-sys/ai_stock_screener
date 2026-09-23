import Link from "next/link";
import { Clock } from "lucide-react";

import { cn } from "@/lib/utils";
import { CompanyLogo } from "@/components/company-logo";
import {
  formatDate,
  formatMoney,
  formatMoneyCompact,
  formatPercent,
  MISSING,
} from "@/lib/format";
import { marketPath, type Market } from "@/lib/markets";
import { STATUS_LABEL, historyProgress, statusDetail } from "@/lib/new-listings.mjs";
import type { NewListingRow } from "@/lib/queries";

/**
 * "Not yet rated" rather than a rating-coloured chip. A new listing has no
 * position on the STRONG BUY -> SELL scale, and borrowing any of its colours
 * would imply one; the neutral chip with a clock says "waiting", which is the
 * whole state.
 */
export function NotRatedBadge({
  className,
  size = "sm",
}: {
  className?: string;
  size?: "sm" | "md";
}) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border border-dashed border-border bg-(--control) font-semibold tracking-[0.02em] text-muted-foreground uppercase",
        size === "md" ? "px-2.5 py-1 text-[11px]" : "px-2 py-0.5 text-[10px]",
        className,
      )}
    >
      <Clock className={size === "md" ? "size-3.5" : "size-3"} aria-hidden />
      Not yet rated
    </span>
  );
}

/** Sessions of price history against the model's minimum. */
export function HistoryBar({ row, className }: { row: NewListingRow; className?: string }) {
  const progress = historyProgress(row);
  const complete = progress >= 1;
  return (
    <div className={cn("space-y-1", className)}>
      <div
        role="meter"
        aria-label="Price history toward the rating minimum"
        aria-valuemin={0}
        aria-valuemax={row.sessions_required}
        aria-valuenow={Math.min(row.sessions ?? 0, row.sessions_required)}
        className="h-1.5 overflow-hidden rounded-full bg-(--control)"
      >
        <div
          className={cn(
            "bar-grow h-full rounded-full",
            complete ? "bg-positive" : "bg-foreground/70",
          )}
          style={{ width: `${Math.max(progress * 100, 2)}%` }}
        />
      </div>
      <p className="tabular text-[11px] text-muted-foreground">
        {row.sessions ?? 0} / {row.sessions_required} sessions
      </p>
    </div>
  );
}

function changeTone(value: number | null) {
  if (value == null || value === 0) return "";
  return value > 0 ? "text-positive" : "text-negative";
}

export function listingDetail(row: NewListingRow, market: Market) {
  return statusDetail(row, (value: number | null) => formatMoneyCompact(value, market));
}

/**
 * The New listings list. A table from `md`, cards below it: seven columns do
 * not fit a phone, and a horizontally scrolling list of companies hides the
 * reason each one is waiting, which is the point of the page.
 */
export function NewListingsList({ rows, market }: { rows: NewListingRow[]; market: Market }) {
  const href = (symbol: string) =>
    marketPath(market.slug, `/stocks/${encodeURIComponent(symbol)}`);

  return (
    <>
      <ul className="divide-y md:hidden">
        {rows.map((row) => (
          <li key={row.symbol}>
            <Link
              href={href(row.symbol)}
              className="press flex gap-3 px-4 py-3.5 active:bg-(--control) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
            >
              <CompanyLogo symbol={row.symbol} domain={row.logo_domain} />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-mono text-sm font-semibold">{row.symbol}</span>
                  <span className="tabular text-sm font-semibold">
                    {formatMoney(row.last_close, market)}
                  </span>
                </div>
                <div className="flex items-baseline justify-between gap-3">
                  <span className="truncate text-xs text-muted-foreground">
                    {row.company ?? MISSING}
                  </span>
                  <span className={cn("tabular shrink-0 text-xs", changeTone(row.change_since_first_pct))}>
                    {formatPercent(row.change_since_first_pct, 1, true)}
                  </span>
                </div>
                <div className="mt-2 flex items-center justify-between gap-3">
                  <span className="text-[11px] text-muted-foreground">
                    Listed {formatDate(row.listed_on)} · {STATUS_LABEL[row.status]}
                  </span>
                </div>
                {row.status === "insufficient_history" ? (
                  <HistoryBar row={row} className="mt-1.5" />
                ) : null}
              </div>
            </Link>
          </li>
        ))}
      </ul>

      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th scope="col" className="sticky-head px-4 py-2.5 font-medium">Stock</th>
              <th scope="col" className="sticky-head px-4 py-2.5 font-medium">Listed</th>
              <th scope="col" className="sticky-head px-4 py-2.5 text-right font-medium">Price</th>
              <th scope="col" className="sticky-head px-4 py-2.5 text-right font-medium" title="Change since the first close the price source reports">
                Since first close
              </th>
              <th scope="col" className="sticky-head px-4 py-2.5 text-right font-medium">Market cap</th>
              <th scope="col" className="sticky-head px-4 py-2.5 font-medium">History</th>
              <th scope="col" className="sticky-head px-4 py-2.5 font-medium">Why not rated</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((row) => (
              <tr key={row.symbol} className="group transition-colors hover:bg-(--control)">
                <td className="px-4 py-3">
                  <Link
                    href={href(row.symbol)}
                    className="flex items-center gap-3 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <CompanyLogo symbol={row.symbol} domain={row.logo_domain} />
                    <span className="min-w-0">
                      <span className="block font-mono text-sm font-semibold">{row.symbol}</span>
                      <span className="block max-w-[16rem] truncate text-xs text-muted-foreground">
                        {row.company ?? MISSING}
                      </span>
                    </span>
                  </Link>
                </td>
                <td className="tabular px-4 py-3 whitespace-nowrap text-muted-foreground">
                  {formatDate(row.listed_on)}
                </td>
                <td className="tabular px-4 py-3 text-right font-semibold">
                  {formatMoney(row.last_close, market)}
                </td>
                <td className={cn("tabular px-4 py-3 text-right", changeTone(row.change_since_first_pct))}>
                  {formatPercent(row.change_since_first_pct, 1, true)}
                </td>
                <td className="tabular px-4 py-3 text-right text-muted-foreground">
                  {formatMoneyCompact(row.market_cap, market)}
                </td>
                <td className="w-36 px-4 py-3">
                  <HistoryBar row={row} />
                </td>
                <td className="max-w-[22rem] px-4 py-3">
                  <p className="text-xs font-medium">{STATUS_LABEL[row.status]}</p>
                  <p className="mt-0.5 text-xs leading-snug text-muted-foreground">
                    {listingDetail(row, market)}
                  </p>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
