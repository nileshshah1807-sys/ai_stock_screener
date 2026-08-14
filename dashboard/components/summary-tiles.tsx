import Link from "next/link";

import { cn } from "@/lib/utils";
import { CountUp, Reveal } from "@/components/motion";
import type { ScreenerRun } from "@/lib/types";

/**
 * Rating mix for the run.
 *
 * These are counts, not a chart: five numbers with no trend and no part-to-whole
 * question worth a pie. A stat tile answers "how many BUYs today" in one glance,
 * and each tile links into the grid pre-filtered to that rating so the number is
 * a starting point rather than a dead end.
 *
 * Presentation follows the Figma KPI band (node 1:1092): one panel rather than
 * six floating cards, hairline dividers between cells, a small muted label over
 * a large display figure, and a rounded vertical accent bar carrying the
 * rating's hue. The mock sets its figure at 64px across three cells; at six
 * cells the same proportion lands near 48px, so the scale below tops out there
 * rather than reproducing the literal pixel value into a column half the width.
 */
const TILES = [
  {
    rating: "STRONG BUY",
    field: "strong_buy_count",
    rule: "bg-rating-strong-buy ring-rating-strong-buy-edge",
  },
  {
    rating: "BUY",
    field: "buy_count",
    rule: "bg-rating-buy ring-rating-buy-edge",
  },
  {
    rating: "HOLD",
    field: "hold_count",
    rule: "bg-rating-hold ring-rating-hold-edge",
  },
  {
    rating: "REDUCE",
    field: "reduce_count",
    rule: "bg-rating-reduce ring-rating-reduce-edge",
  },
  {
    rating: "SELL",
    field: "sell_count",
    rule: "bg-rating-sell ring-rating-sell-edge",
  },
] as const;

/**
 * The mock's accent bar: 8px wide, fully rounded, full cell height.
 *
 * The inset ring is required, not cosmetic. Four of the five rating fills sit
 * between 1.4:1 and 1.8:1 against the light card, so the ring -- a darker step
 * of the bar's own hue -- is what gives it a boundary at all.
 */
function AccentBar({ className }: { className: string }) {
  return (
    <span
      className={cn(
        "h-11 w-2 shrink-0 rounded-full ring-1 ring-inset",
        "origin-center transition-transform duration-(--duration-slow) ease-(--ease-spring)",
        "group-hover:scale-y-115",
        className,
      )}
      aria-hidden
    />
  );
}

export function SummaryTiles({ run }: { run: ScreenerRun }) {
  const total = run.row_count || 0;

  return (
    /*
     * Dividers come from a 1px grid gap over the border colour rather than
     * per-cell borders. At three breakpoints the "which cell is last in its
     * row" arithmetic that per-cell borders need is both unreadable and wrong
     * the moment a column count changes; the gap is correct at every width by
     * construction.
     */
    <Reveal
      selector="[data-kpi]"
      bounce
      className="panel grid grid-cols-2 gap-px overflow-hidden bg-border sm:grid-cols-3 xl:grid-cols-6"
    >
      <div data-kpi className="flex items-center gap-3 bg-card p-4">
        <AccentBar className="bg-muted-foreground/40 ring-muted-foreground/30" />
        <div className="min-w-0">
          <p className="truncate text-[13px] text-muted-foreground">Universe</p>
          <p className="flex items-baseline gap-1.5">
            <CountUp
              value={total}
              className="numeral text-3xl font-semibold sm:text-4xl xl:text-5xl"
            />
          </p>
          <p className="text-[11px] text-muted-foreground">scored</p>
        </div>
      </div>

      {TILES.map((tile) => {
        const count = (run[tile.field] as number) ?? 0;
        const share = total ? (count / total) * 100 : 0;

        return (
          <Link
            key={tile.rating}
            href={`/?rating=${encodeURIComponent(tile.rating)}`}
            data-kpi
            className={cn(
              "press group flex items-center gap-3 bg-card p-4",
              "hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
            )}
          >
            <AccentBar className={tile.rule} />
            <div className="min-w-0">
              {/* The label stays sentence-cased at 13px rather than the old
                  uppercase micro-label: at this figure size the caps were
                  competing with the number instead of introducing it. */}
              <p className="truncate text-[13px] text-muted-foreground">
                {tile.rating}
              </p>
              {/*
                The figure is foreground-coloured, not rating-coloured, which
                is what the mock does: its three KPI numbers are all #1c1b1b
                and only the accent bar carries hue. That is also the only
                readable option here -- amber as 48px text on the light card
                measures 1.45:1, below even the 3:1 large-text floor.
              */}
              <p className="flex items-baseline gap-1.5">
                <CountUp
                  value={count}
                  className="numeral text-3xl font-semibold sm:text-4xl xl:text-5xl"
                />
              </p>
              <p className="tabular text-[11px] text-muted-foreground">
                {share.toFixed(1)}% of run
              </p>
            </div>
          </Link>
        );
      })}
    </Reveal>
  );
}
