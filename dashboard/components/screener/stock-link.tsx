"use client";

import Link from "next/link";

import { CompanyLogo } from "@/components/company-logo";
import { useMarketPath } from "@/components/market-provider";
import { MISSING } from "@/lib/format";
import type { SnapshotRow } from "@/lib/types";

/**
 * The grid's identity cell: logo, ticker, company, linked to the stock page.
 *
 * A client component purely so it can read the current market from context.
 * The alternative was passing the market into every entry of the `CELLS`
 * record in screener-table.tsx -- sixty renderers, of which exactly one needs
 * it -- and a forgotten one would be a broken link at runtime rather than a
 * type error.
 */
export function StockLink({ row }: { row: SnapshotRow }) {
  const marketPath = useMarketPath();

  return (
    <Link
      href={marketPath(`/stocks/${encodeURIComponent(row.symbol)}`)}
      // Read by GridKeyboard to find the next row to focus. A class or a tag
      // selector would also match links inside cells, and j/k would then walk
      // sideways through a row instead of down the column.
      data-row-link
      /*
       * 100 rows means 100 prefetches per page view, each one a proxy
       * invocation, to serve the at most one row the reader actually clicks.
       * The trace showed exactly that: a wall of `/stocks/XXX` proxy lines
       * after every grid render.
       *
       * Turning it off costs almost nothing here because the route has its own
       * loading.tsx. That Suspense boundary renders the moment navigation
       * starts, prefetched or not, and the page's data is fetched on click
       * either way -- a dynamic route's prefetch stops at the loading boundary.
       * So the prefetch was buying a shell that appears anyway.
       */
      prefetch={false}
      className="flex items-center gap-2 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <CompanyLogo symbol={row.symbol} domain={row.logo_domain} />
      {/* Explicitly capped, not just min-w-0. The cell is fixed at
          --sticky-col-w so the second frozen column can offset by exactly that,
          but an auto-layout table treats a td width as a hint and will still
          widen it if a child asks to be wider. 8rem is --sticky-col-w less the
          cell padding, the 32px logo and its gap. */}
      <span className="min-w-0 max-w-[8rem]">
        {/* Underline alone, no colour shift: --primary and --foreground are
            within a hair of each other in both themes, so a colour hover would
            be invisible. */}
        <span className="block truncate font-mono text-xs font-semibold underline-offset-2 group-hover:underline">
          {row.symbol}
        </span>
        <span className="block truncate text-[11px] text-muted-foreground">
          {row.company ?? MISSING}
        </span>
      </span>
    </Link>
  );
}
