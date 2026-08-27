import type { ReactNode } from "react";
import Link from "next/link";

import { CompanyLogo } from "@/components/company-logo";
import { EntryBadge } from "@/components/entry-badge";
import {
  CappedChip,
  CoverageCell,
  RedFlagChip,
  TranscriptChip,
} from "@/components/evidence-chips";
import { GridKeyboard } from "@/components/screener/grid-keyboard";
import { PlainHeader, SortHeader } from "@/components/screener/sort-header";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { dcfStatus } from "@/lib/labels";
import { visibleColumns, type ColumnId, type Density } from "@/lib/columns";
import {
  formatINR,
  formatINRCompact,
  formatNumber,
  formatPercent,
  formatScore,
  ratingToken,
  MISSING,
} from "@/lib/format";
import type { SnapshotRow } from "@/lib/types";

/**
 * Signed change cell. Sign is carried by an explicit +/- and by position, so
 * colour is reinforcement rather than the only signal.
 *
 * `decimals` exists for the 1D column: a single session's move is usually
 * inside a percent, so one decimal rounds most of the column to the same two
 * or three values and destroys the ordering the reader is scanning for. It
 * also keeps the grid's 1D figure identical to the stock page's 1D tile.
 */
function ChangeCell({
  value,
  decimals = 1,
}: {
  value: number | null;
  decimals?: number;
}) {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground">{MISSING}</span>;
  }
  return (
    <span
      className={cn(
        "tabular",
        value > 0 ? "text-positive" : value < 0 ? "text-negative" : "",
      )}
    >
      {formatPercent(value, decimals, true)}
    </span>
  );
}

/**
 * A 2px rule under the decision score showing where it sits on 0-100.
 *
 * A column of bare four-character numbers gives the eye nothing to grab: to
 * compare two rows you have to actually read and subtract them. The rule turns
 * the same value into a length, which is pre-attentive -- an outlier is
 * visible while scrolling rather than only on inspection. It carries no
 * information the number does not already carry, so it is decoration in the
 * strict sense, but it is decoration that makes the column scannable.
 *
 * Coloured by rating band so it agrees with the badge two columns to its left.
 */
function ScoreMeter({
  score,
  rating,
}: {
  score: number | null;
  rating: string | null | undefined;
}) {
  if (score === null || score === undefined) return null;
  const pct = Math.max(0, Math.min(100, score));
  return (
    <span
      className="mt-1 block h-0.5 w-full overflow-hidden rounded-full bg-muted"
      aria-hidden
    >
      <span
        className="block h-full rounded-full transition-[width] duration-(--duration-slow) ease-(--ease-entrance)"
        style={{
          width: `${pct}%`,
          background: `var(--rating-${ratingToken(rating)})`,
        }}
      />
    </span>
  );
}

/** True when the row's gates imply a ceiling below its published score. */
function scoreWasReduced(row: SnapshotRow): boolean {
  const published = row.final_score ?? row.evidence_score;
  const ceiling = row.decision_score;
  return (
    published !== null && ceiling !== null && Math.abs(published - ceiling) > 0.05
  );
}

/**
 * The published score, uncapped. One number per row.
 *
 * A row whose evidence scores 99.8 reads 99.8. Publishing the 70.0 ceiling
 * instead destroyed the most useful number on the row and made every capped
 * candidate look identical.
 *
 * The ceiling used to be annotated beside the score as `⌐70.0`. It is now in
 * the tooltip only. Rendered inline it read as a second, worse score competing
 * with the headline figure -- the reader has no reason to know that one of the
 * two numbers is a policy artefact and the other is the evidence, so the cell
 * asked a question instead of answering one.
 *
 * The *rating* is still gated, and the `EntryBadge` in the next column carries
 * that: a gated row reads `WAIT · below 200DMA` rather than `HOLD`, which is a
 * statement about timing and so does not compete with the score for the same
 * meaning.
 */
function ScoreCell({ row }: { row: SnapshotRow }) {
  const published = row.final_score ?? row.evidence_score;
  const ceiling = row.decision_score;
  const capped = scoreWasReduced(row);

  if (!capped) {
    return (
      <span className="inline-block w-[3.25rem] align-middle">
        <span className="tabular font-mono text-sm font-semibold">
          {formatScore(published)}
        </span>
        <ScoreMeter score={published} rating={row.rating} />
      </span>
    );
  }

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span className="inline-block w-[3.25rem] cursor-help align-middle" />
        }
      >
        <span className="tabular font-mono text-sm font-semibold">
          {formatScore(published)}
        </span>
        <ScoreMeter score={published} rating={row.rating} />
      </TooltipTrigger>
      <TooltipContent className="max-w-72">
        <p className="font-medium">Rating limited by a policy gate</p>
        <p className="text-xs opacity-90">
          Evidence scored {formatScore(published)}. Policy gates cap the rating
          at {row.policy_eligible_rating ?? "a lower band"} (ceiling{" "}
          {formatScore(ceiling)}); the score itself is published in full.
        </p>
        {row.decision_cap_reason || row.rating_cap_reason ? (
          <p className="mt-1 text-xs opacity-90">
            {row.decision_cap_reason || row.rating_cap_reason}
          </p>
        ) : null}
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * A factor percentile, shown as a rank within the cross-section.
 *
 * Rendered as "P72" rather than a bare 72 because these are percentiles, not
 * scores on the same 0-100 scale as Decision. Conflating the two would invite
 * reading a quality percentile as if it were a rating band.
 */
function PercentileCell({ value }: { value: number | null }) {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground">{MISSING}</span>;
  }
  return (
    <span
      className={cn(
        "tabular font-mono text-xs",
        value >= 70 ? "text-positive" : value < 30 ? "text-negative" : "",
      )}
    >
      P{Math.round(value)}
    </span>
  );
}

function DcfCell({ row }: { row: SnapshotRow }) {
  if (row.dcf_status && row.dcf_base_case_upside !== null) {
    return <ChangeCell value={(row.dcf_base_case_upside ?? 0) * 100} />;
  }
  return (
    <Tooltip>
      <TooltipTrigger
        render={<span className="cursor-help text-muted-foreground" />}
      >
        {MISSING}
      </TooltipTrigger>
      <TooltipContent className="max-w-72">
        <p className="font-medium">{dcfStatus(row.dcf_status).label}</p>
        <p className="text-xs opacity-90">
          {dcfStatus(row.dcf_status).meaning ||
            "No usable DCF result. Treated as neutral evidence, not as a negative signal."}
        </p>
      </TooltipContent>
    </Tooltip>
  );
}

function LiquidityCell({ row }: { row: SnapshotRow }) {
  if (!row.liquidity_grade) {
    return <span className="text-xs text-muted-foreground">{MISSING}</span>;
  }
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            className={cn(
              "tabular cursor-help font-mono text-xs",
              row.portfolio_actionable ? "text-foreground" : "text-caution",
            )}
          />
        }
      >
        {row.liquidity_grade}
      </TooltipTrigger>
      <TooltipContent className="max-w-64">
        <p className="text-xs">
          {row.portfolio_actionable
            ? "The configured target position is executable at the assumed participation rate."
            : "Not executable at the configured target position. This does not change the score or rating."}
        </p>
        <p className="mt-1 text-xs opacity-80">
          20-day median turnover{" "}
          {formatINRCompact(row.median_turnover_20d_inr)}
        </p>
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * Cell renderers, keyed by the same ids the registry uses.
 *
 * Split from `lib/columns.ts` only because that file has to stay JSX-free to be
 * importable by the server-side query builder. Keeping the keys identical is
 * what ties a column's metadata to its rendering; TypeScript enforces that this
 * record is exhaustive, so a registry entry cannot ship without a cell.
 */
const CELLS: Record<ColumnId, (row: SnapshotRow) => ReactNode> = {
  rank: (row) => row.investment_rank ?? MISSING,
  stock: (row) => (
    <Link
      href={`/stocks/${row.symbol}`}
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
  ),
  score: (row) => <ScoreCell row={row} />,
  quality: (row) => <PercentileCell value={row.quality_percentile} />,
  momentum: (row) => <PercentileCell value={row.momentum_percentile} />,
  growth: (row) => <PercentileCell value={row.growth_percentile} />,
  fundamental: (row) => formatScore(row.fundamental_score),
  technical: (row) => formatScore(row.technical_score),
  rating: (row) => <EntryBadge row={row} />,
  coverage: (row) => (
    <CoverageCell
      fundamental={row.fundamental_coverage}
      technical={row.technical_coverage}
    />
  ),
  dcf: (row) => <DcfCell row={row} />,
  evidence: (row) => (
    <span className="flex items-center gap-1.5">
      <TranscriptChip
        status={row.transcript_status}
        eligible={row.transcript_scoring_eligible}
        guidance={row.transcript_guidance}
      />
      <RedFlagChip
        status={row.red_flag_status}
        severity={row.red_flag_severity}
        wouldChange={row.shadow_red_flag_would_change}
      />
      <CappedChip
        capped={row.rating_capped}
        reason={row.rating_cap_reason ?? row.decision_cap_reason}
        enforced={scoreWasReduced(row)}
      />
    </span>
  ),
  price: (row) => formatINR(row.current_price, 0),
  change1d: (row) => <ChangeCell value={row.pct_change_1d} decimals={2} />,
  change1m: (row) => <ChangeCell value={row.pct_change_1m} />,
  marketCap: (row) => formatINRCompact(row.market_cap),
  pe: (row) => formatNumber(row.pe_ratio, 1),
  liq: (row) => <LiquidityCell row={row} />,
};

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
      <div className="grid-scroll">
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

          <tbody>
            {rows.map((row) => (
              <tr
                key={row.symbol}
                className={cn(
                  "group border-t transition-colors duration-(--duration-fast) ease-(--ease-standard)",
                  // focus-within, not just hover: keyboard traversal down the
                  // grid highlights the same band the mouse would.
                  "hover:bg-muted/40 focus-within:bg-muted/40",
                )}
              >
                {columns.map((column) => (
                  <td
                    key={column.id}
                    className={cn("grid-cell", column.cellClassName)}
                  >
                    {CELLS[column.id](row)}
                  </td>
                ))}
                {rowAction ? (
                  <td className="grid-cell sticky-col-right text-right">
                    {rowAction.render(row)}
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
