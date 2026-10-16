"use client";

import { StockIdentity } from "@/components/stock-identity";
import type { SnapshotRow } from "@/lib/types";

/**
 * The grid's identity cell: logo, ticker, company, linked to the stock page.
 *
 * The grid's own use of the shared StockIdentity. The row already carries
 * the company and logo, so nothing is looked up.
 */
export function StockLink({ row }: { row: SnapshotRow }) {
  return (
    <StockIdentity
      symbol={row.symbol}
      company={row.company}
      logoDomain={row.logo_domain}
      // Read by GridKeyboard to find the next row to focus.
      rowLink
      // Explicitly capped, not just min-w-0. The cell is fixed at
      // --sticky-col-w so the second frozen column can offset by exactly
      // that, but an auto-layout table treats a td width as a hint and will
      // still widen it if a child asks to be wider. 8rem is --sticky-col-w
      // less the cell padding, the 32px logo and its gap.
      textClassName="max-w-[8rem]"
    />
  );
}
