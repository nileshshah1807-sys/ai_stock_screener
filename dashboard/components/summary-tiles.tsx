import Link from "next/link";

import { cn } from "@/lib/utils";
import { formatInteger } from "@/lib/format";
import type { ScreenerRun } from "@/lib/types";

/**
 * Rating mix for the run.
 *
 * These are counts, not a chart: five numbers with no trend and no part-to-whole
 * question worth a pie. A stat tile answers "how many BUYs today" in one glance,
 * and each tile links into the grid pre-filtered to that rating so the number is
 * a starting point rather than a dead end.
 */
const TILES = [
  {
    rating: "STRONG BUY",
    field: "strong_buy_count",
    accent: "text-rating-strong-buy",
    rule: "bg-rating-strong-buy",
  },
  {
    rating: "BUY",
    field: "buy_count",
    accent: "text-rating-buy",
    rule: "bg-rating-buy",
  },
  {
    rating: "HOLD",
    field: "hold_count",
    accent: "text-rating-hold",
    rule: "bg-rating-hold",
  },
  {
    rating: "REDUCE",
    field: "reduce_count",
    accent: "text-rating-reduce",
    rule: "bg-rating-reduce",
  },
  {
    rating: "SELL",
    field: "sell_count",
    accent: "text-rating-sell",
    rule: "bg-rating-sell",
  },
] as const;

export function SummaryTiles({ run }: { run: ScreenerRun }) {
  const total = run.row_count || 0;

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
      <div className="flex min-h-24 flex-col justify-between rounded border bg-card p-3">
        <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Universe
        </p>
        <p>
          <span className="tabular font-mono text-2xl font-semibold">
            {formatInteger(total)}
          </span>
          <span className="ml-1.5 text-[11px] text-muted-foreground">
            scored
          </span>
        </p>
      </div>

      {TILES.map((tile) => {
        const count = (run[tile.field] as number) ?? 0;
        const share = total ? (count / total) * 100 : 0;

        return (
          <Link
            key={tile.rating}
            href={`/?rating=${encodeURIComponent(tile.rating)}`}
            className={cn(
              "group relative flex min-h-24 flex-col justify-between overflow-hidden rounded border bg-card p-3 transition-colors",
              "hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            )}
          >
            {/* A 2px rule rather than a tinted card: the hue marks the tile
                without competing with the figure for attention. */}
            <span
              className={cn("absolute inset-x-0 top-0 h-0.5", tile.rule)}
              aria-hidden
            />
            <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              {tile.rating}
            </p>
            <p className="flex items-baseline gap-1.5">
              <span
                className={cn(
                  "tabular font-mono text-2xl font-semibold",
                  tile.accent,
                )}
              >
                {formatInteger(count)}
              </span>
              <span className="tabular text-[11px] text-muted-foreground">
                {share.toFixed(1)}%
              </span>
            </p>
          </Link>
        );
      })}
    </div>
  );
}
