import { HistoryBar, NotRatedBadge } from "@/components/new-listing";
import { StockIdentity } from "@/components/stock-identity";
import { formatDate, formatMoney, formatMoneyCompact, formatPercent } from "@/lib/format";
import type { Market } from "@/lib/markets";
import type { NewListingRow } from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * Recent listings the run has not rated, after the last ranked row. A table of
 * its own rather than rows of the grid: it has no score, rank or factor to
 * put under the grid's columns, and nothing here sorts or filters on one.
 */
export function NotRatedRows({ rows, market }: { rows: NewListingRow[]; market: Market }) {
  if (!rows.length) return null;
  return (
    <section className="panel overflow-hidden" aria-labelledby="not-rated-heading">
      <div className="border-b px-4 py-3">
        <h2 id="not-rated-heading" className="text-sm font-semibold">
          Not rated <span className="tabular font-normal text-muted-foreground">· {rows.length} recent listings</span>
        </h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Listed too recently for a rating; they have no score or rank and are not in the export.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th scope="col" className="px-4 py-2 font-medium">Stock</th>
              <th scope="col" className="px-4 py-2 font-medium">Rating</th>
              <th scope="col" className="px-4 py-2 font-medium">Listed</th>
              <th scope="col" className="px-4 py-2 text-right font-medium">Price</th>
              <th scope="col" className="px-4 py-2 text-right font-medium">Since first close</th>
              <th scope="col" className="px-4 py-2 text-right font-medium">Market cap</th>
              <th scope="col" className="px-4 py-2 font-medium">History</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((row) => (
              <tr key={row.symbol} className="hover:bg-(--control)">
                <td className="px-4 py-2.5">
                  <StockIdentity symbol={row.symbol} company={row.company} logoDomain={row.logo_domain} textClassName="max-w-[16rem]" />
                </td>
                <td className="px-4 py-2.5"><NotRatedBadge /></td>
                <td className="tabular whitespace-nowrap px-4 py-2.5 text-muted-foreground">
                  {formatDate(row.listed_on)}
                </td>
                <td className="tabular px-4 py-2.5 text-right">{formatMoney(row.last_close, market)}</td>
                <td
                  className={cn(
                    "tabular px-4 py-2.5 text-right",
                    (row.change_since_first_pct ?? 0) > 0 && "text-positive",
                    (row.change_since_first_pct ?? 0) < 0 && "text-negative",
                  )}
                >
                  {formatPercent(row.change_since_first_pct, 1, true)}
                </td>
                <td className="tabular px-4 py-2.5 text-right text-muted-foreground">
                  {formatMoneyCompact(row.market_cap, market)}
                </td>
                <td className="w-36 px-4 py-2.5"><HistoryBar row={row} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
