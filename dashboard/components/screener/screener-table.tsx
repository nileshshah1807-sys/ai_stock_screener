import type { ReactNode } from "react";

import { GridKeyboard } from "@/components/screener/grid-keyboard";
import { GridScroll } from "@/components/screener/grid-scroll";
import { ScreenerRows } from "@/components/screener/screener-rows";
import { PlainHeader, SortHeader } from "@/components/screener/sort-header";
import { visibleColumns, type ColumnId, type Density } from "@/lib/columns";
import { cn } from "@/lib/utils";
import type { SnapshotRow } from "@/lib/types";

/*
 * The standalone Gate column was removed. It restated what the RATING cell's
 * EntryBadge already says -- that badge reads the same `primary_gate` and adds
 * the distance still to clear ("2.3% below 200DMA"), which the bare chip could
 * not -- so the two columns competed to answer one question while costing the
 * grid its widest non-numeric column. The full binding-gate detail, including
 * simultaneous-failure count, stays on the stock page's Decision audit.
 */

/**
 * An optional trailing column of per-row controls.
 *
 * This is how the watchlist page reuses this table rather than forking it. The
 * screener renders the grid with no action; the watchlist renders the same grid
 * with a remove control. Everything else -- the registry, the projection, the
 * frozen columns, sorting, density, keyboard traversal -- is shared, so a change
 * to any of it lands on both pages at once.
 *
 * A render prop rather than a registry entry because the cell needs data the
 * snapshot row does not carry: which list this row is being shown in.
 */
export type RowAction = {
  /** Header text. Kept for screen readers even when visually empty. */
  label: string;
  render: (row: SnapshotRow) => ReactNode;
};

export function ScreenerTable({
  rows,
  params,
  sort,
  dir,
  hiddenColumns = [],
  density = "compact",
  rowAction,
  emptyState,
}: {
  rows: SnapshotRow[];
  params: URLSearchParams;
  sort: string;
  dir: "asc" | "desc";
  hiddenColumns?: ColumnId[];
  density?: Density;
  rowAction?: RowAction;
  /**
   * Replaces the default "no stocks match these filters" panel. An empty
   * watchlist and an over-filtered screener are different situations and need
   * different sentences.
   */
  emptyState?: ReactNode;
}) {
  const headerProps = { currentSort: sort, currentDir: dir, params };
  // A run is either 4.x or Model 5.0 for its whole cross-section, so one row
  // settles it. Showing both column sets would double the grid width and leave
  // whichever model did not run as a full column of dashes.
  const factorModel = rows.some((row) => row.factor_model_applied === true);
  const columns = visibleColumns(hiddenColumns, factorModel);

  if (!rows.length) {
    return (
      emptyState ?? (
        <div className="panel animate-rise py-16 text-center">
          <p className="text-sm font-medium">No stocks match these filters</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Try widening the rating selection or clearing the evidence filters.
          </p>
        </div>
      )
    );
  }

  return (
    /*
     * The grid fades in as one object, not row by row. A staggered reveal is
     * right for six KPI tiles and wrong here: at a full page of rows even a
     * 20ms step runs for seconds, and it delays the one thing the reader came
     * for. One 180ms fade on the whole panel, then the numbers are readable.
     */
    <div className="panel animate-fade overflow-hidden">
      <GridKeyboard />
      {/* The grid is wider than a phone and legitimately so: it is a
          cross-sectional comparison. It scrolls inside its own container so the
          page body never scrolls sideways -- and, now that the container has a
          bounded height, so the header row stays put on the way down. See
          `.grid-scroll` for why the bound is what makes that work. */}
      <GridScroll>
        <table
          className={cn(
            "w-full border-collapse text-sm",
            density === "comfortable"
              ? "grid-density-comfortable"
              : "grid-density-compact",
          )}
        >
          <caption className="sr-only">
            Screened NSE stocks ordered by {sort.replace(/_/g, " ")}, showing
            model decision score, evidence coverage, and execution suitability.
          </caption>
          <thead className="sticky-head">
            <tr>
              {columns.map((column) =>
                column.sort ? (
                  <SortHeader
                    key={column.id}
                    {...headerProps}
                    label={column.label}
                    column={column.sort}
                    numeric={column.numeric}
                    defaultDir={column.defaultDir}
                    className={column.headerClassName}
                    title={column.title}
                  />
                ) : (
                  <PlainHeader
                    key={column.id}
                    label={column.label}
                    numeric={column.numeric}
                    className={column.headerClassName}
                    title={column.title}
                  />
                ),
              )}
              {rowAction ? (
                <PlainHeader
                  label={rowAction.label}
                  className="sticky-col-right"
                />
              ) : null}
            </tr>
          </thead>

          <ScreenerRows
            rows={rows}
            hiddenColumns={hiddenColumns}
            factorModel={factorModel}
            // The action is a render prop and cannot cross to the client, so
            // its cells are rendered here and handed over by symbol.
            actions={
              rowAction
                ? Object.fromEntries(rows.map((row) => [row.symbol, rowAction.render(row)]))
                : undefined
            }
          />
        </table>
      </GridScroll>
    </div>
  );
}
