"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { CompanyLogo } from "@/components/company-logo";
import { useMarket } from "@/components/market-provider";
import { SymbolText } from "@/components/symbol-text";
import { MISSING } from "@/lib/format";
import { marketPath } from "@/lib/markets";
import { useStockEntry } from "@/lib/stock-directory";
import { cn } from "@/lib/utils";

/*
 * How the dashboard names a stock: its logo, ticker and company, linked to
 * its page. One component, so a list on the Market page looks like a row of
 * the screener, and a fix to one is a fix to all.
 *
 * Pass what the row already has. A fact left `undefined` -- not null, which
 * means "known to be missing" -- is filled from the market's stock directory
 * (lib/stock-directory.ts), so a row that knows only a symbol still shows
 * the company and its logo.
 */

const SIZES = {
  sm: { symbol: "text-xs font-semibold", line: "text-[11px]" },
  md: { symbol: "text-sm font-semibold", line: "text-xs" },
} as const;

function useStockHref(symbol: string): string {
  return marketPath(useMarket().slug, `/stocks/${encodeURIComponent(symbol)}`);
}

export function StockIdentity({
  symbol,
  company,
  logoDomain,
  link = true,
  size = "sm",
  emphasis = "symbol",
  subtitle,
  rowLink = false,
  className,
  textClassName,
}: {
  symbol: string;
  company?: string | null;
  logoDomain?: string | null;
  /** False when the caller's row is itself the link or the button. */
  link?: boolean;
  size?: keyof typeof SIZES;
  /** "company" leads with the name and puts the ticker under it, for a card's title. */
  emphasis?: "symbol" | "company";
  /** Replaces the company line, e.g. a trade's dates. */
  subtitle?: ReactNode;
  /** Marks the link for the grid's j/k keyboard walk (see GridKeyboard). */
  rowLink?: boolean;
  className?: string;
  /** Width cap on the text, where the column is fixed. */
  textClassName?: string;
}) {
  const market = useMarket();
  const entry = useStockEntry(
    market.slug,
    symbol,
    company === undefined || logoDomain === undefined,
  );
  const name = company !== undefined ? company : entry?.c || null;
  const domain = logoDomain !== undefined ? logoDomain : (entry?.l ?? null);
  const href = useStockHref(symbol);
  const sizes = SIZES[size];

  const text =
    emphasis === "company" ? (
      <span className={cn("min-w-0", textClassName)}>
        <span className="block truncate text-base font-semibold tracking-[-0.011em] underline-offset-2 group-hover:underline">
          {name ?? symbol}
        </span>
        {name ? <span className="block font-mono text-xs text-muted-foreground"><SymbolText symbol={symbol} /></span> : null}
      </span>
    ) : (
      <span className={cn("min-w-0", textClassName)}>
        {/* Underline alone, no colour shift: --primary and --foreground are
            within a hair of each other in both themes. */}
        <span
          className={cn(
            "block truncate font-mono underline-offset-2 group-hover:underline",
            sizes.symbol,
          )}
        >
          <SymbolText symbol={symbol} />
        </span>
        <span className={cn("block truncate text-muted-foreground", sizes.line)}>
          {subtitle ?? name ?? MISSING}
        </span>
      </span>
    );

  const body = (
    <>
      <CompanyLogo symbol={symbol} domain={domain} />
      {text}
    </>
  );
  const layout = cn("flex min-w-0 items-center", emphasis === "company" ? "gap-2.5" : "gap-2");

  if (!link) return <span className={cn(layout, className)}>{body}</span>;
  return (
    <Link
      href={href}
      // A list of stocks would prefetch as many stock pages to serve the one
      // the reader opens; the route's loading.tsx shows at once either way.
      prefetch={false}
      data-row-link={rowLink || undefined}
      className={cn(
        "group rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        layout,
        className,
      )}
    >
      {body}
    </Link>
  );
}

/**
 * A stock as one line of a list: rank, identity, then whatever the list adds
 * -- price, change, rating. The whole line opens the stock page.
 *
 * `rank` left `undefined` comes from the directory, like the company and logo.
 * `linked={false}` for a stock with no page (an index member the run does not
 * rate).
 */
export function StockListRow({
  symbol,
  company,
  logoDomain,
  rank,
  linked = true,
  children,
}: {
  symbol: string;
  company?: string | null;
  logoDomain?: string | null;
  rank?: number | null;
  linked?: boolean;
  children?: ReactNode;
}) {
  const market = useMarket();
  const entry = useStockEntry(market.slug, symbol, rank === undefined);
  const href = useStockHref(symbol);
  const shownRank = rank !== undefined ? rank : (entry?.r ?? null);

  const content = (
    <>
      {/* "#" so the figure reads as the screener's rank, not a code. */}
      <span
        className="tabular w-10 shrink-0 font-mono text-xs text-muted-foreground"
        title={shownRank !== null ? "Screener rank" : "Not rated by the screener"}
      >
        {shownRank !== null ? (
          <>
            <span aria-hidden>#{shownRank}</span>
            <span className="sr-only">Rank {shownRank}</span>
          </>
        ) : (
          MISSING
        )}
      </span>
      <StockIdentity
        symbol={symbol}
        company={company}
        logoDomain={logoDomain}
        link={false}
        className="flex-1"
      />
      {children}
    </>
  );
  const rowClass = "flex items-center gap-3 px-4 py-2";

  if (!linked) return <div className={rowClass}>{content}</div>;
  return (
    <Link
      href={href}
      prefetch={false}
      className={cn(
        "group transition-colors duration-(--duration-fast) ease-(--ease-standard) hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
        rowClass,
      )}
    >
      {content}
    </Link>
  );
}
