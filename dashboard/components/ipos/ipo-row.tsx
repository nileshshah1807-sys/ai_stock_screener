import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { StockIdentity } from "@/components/stock-identity";
import { MISSING, formatDate, formatMoney, formatMoneyCompact } from "@/lib/format";
import type { Ipo } from "@/lib/ipos";
import {
  bookSize,
  categoryTimes,
  changeFromIssue,
  formatSignedPercent,
  formatTimes,
  issueStatus,
  minInvestment,
} from "@/lib/ipos.mjs";
import { marketPath, type Market } from "@/lib/markets";
import { cn } from "@/lib/utils";

/** A day as "20 Nov", the year left to the section it sits in. */
export function shortDate(value: string | null) {
  if (!value) return MISSING;
  return new Date(`${value}T00:00:00+05:30`).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    timeZone: "Asia/Kolkata",
  });
}

/** "₹259–272", or one price once it is fixed. */
export function priceBand(row: Ipo, market: Market) {
  if (row.issue_price != null) return formatMoney(row.issue_price, market, 0);
  if (row.price_low == null || row.price_high == null) return MISSING;
  if (row.price_low === row.price_high) return formatMoney(row.price_high, market, 0);
  return `${formatMoney(row.price_low, market, 0)}–${row.price_high.toLocaleString(market.locale)}`;
}

/** Green above the issue price, red below, muted at it or unknown. */
export function changeTone(value: number | null) {
  return value == null || value === 0 ? "text-muted-foreground" : value > 0 ? "text-positive" : "text-negative";
}

function Measure({ label, value, detail, tone }: { label: string; value: string; detail?: string | null; tone?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className={cn("tabular font-mono text-[13px] font-semibold", tone)}>
        {value}
        {detail ? <span className="ml-1.5 font-normal text-muted-foreground">{detail}</span> : null}
      </dd>
    </div>
  );
}

/** The book in a line: QIB, NII and Retail, the three the market watches. */
function categoryLine(row: Ipo) {
  const parts = ["QIB", "NII", "Retail"]
    .map((name) => [name, formatTimes(categoryTimes(row, name))] as const)
    .filter(([, times]) => times)
    .map(([name, times]) => `${name} ${times}`);
  return parts.length ? parts.join(" · ") : null;
}

/**
 * One issue still in the market: dates, band and lot on the left; the book and
 * the grey market on the right. The whole row opens the issue.
 */
export function IpoRow({ row, market, today }: { row: Ipo; market: Market; today: string }) {
  const status = issueStatus(row, today);
  const when =
    status === "upcoming"
      ? `Opens ${shortDate(row.open_date)} · closes ${shortDate(row.close_date)}`
      : status === "bidding"
        ? row.close_date === today
          ? "Closes today"
          : `Closes ${shortDate(row.close_date)}`
        : `Closed ${shortDate(row.close_date)}`;
  const facts = [
    when,
    priceBand(row, market),
    row.lot_size
      ? `Lot ${row.lot_size.toLocaleString(market.locale)} (${formatMoney(minInvestment(row), market, 0)})`
      : null,
  ].filter(Boolean);

  return (
    <Link
      prefetch={false}
      href={marketPath(market.slug, `/ipos/${encodeURIComponent(row.symbol)}`)}
      className="group flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none"
    >
      <div className="grid min-w-0 flex-1 gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center md:gap-6">
        <div className="min-w-0 space-y-1">
          <StockIdentity
            symbol={row.symbol}
            company={row.company}
            link={false}
            emphasis="company"
            sme={row.board === "SME"}
          />
          <p className="tabular text-xs text-muted-foreground">{facts.join(" · ")}</p>
        </div>
        <dl className="flex flex-wrap items-start gap-x-6 gap-y-2 md:justify-end">
          {status === "upcoming" ? (
            <Measure label="Book at top of band" value={formatMoneyCompact(bookSize(row), market)} />
          ) : (
            <Measure
              label={status === "bidding" ? "Subscribed so far" : "Subscribed"}
              value={formatTimes(row.subscription_total) ?? MISSING}
              detail={categoryLine(row)}
            />
          )}
          {row.gmp != null ? (
            <Measure
              label="GMP (unofficial)"
              value={formatMoney(row.gmp, market, row.gmp % 1 ? 1 : 0)}
              detail={formatSignedPercent(row.gmp_pct, 1)}
              tone={changeTone(row.gmp)}
            />
          ) : null}
        </dl>
      </div>
      <ChevronRight
        className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5"
        aria-hidden
      />
    </Link>
  );
}

/** A listed issue: its listing day against the issue price, and today. */
export function ListedRow({ row, market, now }: { row: Ipo; market: Market; now: number | null }) {
  const cell = "tabular whitespace-nowrap px-3 py-2.5 text-right font-mono text-[13px]";
  const opened = changeFromIssue(row, row.listing_open);
  const closed = changeFromIssue(row, row.listing_close);
  const since = changeFromIssue(row, now);
  return (
    <tr className="border-b transition-colors last:border-b-0 hover:bg-muted/40">
      <th scope="row" className="px-3 py-2.5 text-left font-normal">
        <Link
          prefetch={false}
          href={marketPath(market.slug, `/ipos/${encodeURIComponent(row.symbol)}`)}
          className="block rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <StockIdentity symbol={row.symbol} company={row.company} link={false} sme={row.board === "SME"} />
        </Link>
      </th>
      <td className={cn(cell, "hidden text-muted-foreground sm:table-cell")}>{formatDate(row.listing_date)}</td>
      <td className={cn(cell, "hidden sm:table-cell")}>{formatMoney(row.issue_price ?? row.price_high, market, 0)}</td>
      <td className={cn(cell, changeTone(opened))}>{formatSignedPercent(opened) ?? MISSING}</td>
      <td className={cn(cell, "hidden md:table-cell", changeTone(closed))}>{formatSignedPercent(closed) ?? MISSING}</td>
      <td className={cn(cell, "hidden lg:table-cell")}>{formatTimes(row.subscription_total) ?? MISSING}</td>
      <td className={cell}>
        {now == null ? (
          MISSING
        ) : (
          <>
            <span className="hidden sm:inline">{formatMoney(now, market, 2)}</span>
            <span className={cn("sm:ml-1.5", changeTone(since))}>{formatSignedPercent(since) ?? ""}</span>
          </>
        )}
      </td>
    </tr>
  );
}
