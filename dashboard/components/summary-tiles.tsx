import Link from "next/link";

import { cn } from "@/lib/utils";
import { marketPath, type Market } from "@/lib/markets";
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
 * One panel rather than six floating cards, hairline dividers between cells,
 * a small muted label over
 * a large figure, with the rating's hue carried by a small square key beside
 * the label and a thin bar under the figure showing the band's share of the
 * run -- the same bar the grid draws under every score.
 *
 * The band tops out at 36px rather than 48px, and pads 12px rather than 16px.
 * That is a deliberate departure from the mock, made for the screener page
 * specifically: the grid below is bounded to the viewport so its header can stay
 * pinned, which turns every pixel of chrome above it into a direct trade against
 * rows on screen. The band was ~123px and is now ~100px. Five counts do not need
 * 48px type to be read at a glance, and the rows do need the space.
 */
const TILES = [
  {
    rating: "STRONG BUY",
    field: "strong_buy_count",
    rule: "bg-rating-strong-buy ring-rating-strong-buy-edge",
    fill: "bg-rating-strong-buy",
  },
  {
    rating: "BUY",
    field: "buy_count",
    rule: "bg-rating-buy ring-rating-buy-edge",
    fill: "bg-rating-buy",
  },
  {
    rating: "HOLD",
    field: "hold_count",
    rule: "bg-rating-hold ring-rating-hold-edge",
    fill: "bg-rating-hold-edge",
  },
  {
    rating: "REDUCE",
    field: "reduce_count",
    rule: "bg-rating-reduce ring-rating-reduce-edge",
    fill: "bg-rating-reduce",
  },
  {
    rating: "SELL",
    field: "sell_count",
    rule: "bg-rating-sell ring-rating-sell-edge",
    fill: "bg-rating-sell",
  },
] as const;

/**
 * The band's key: an 8px square of its rating fill beside the label.
 *
 * The inset ring is required, not cosmetic. Four of the five rating fills sit
 * between 1.4:1 and 1.8:1 against the light card, so the ring -- a darker step
 * of the swatch's own hue -- is what gives it a boundary at all.
 */
function Swatch({ className }: { className: string }) {
  return (
    <span
      className={cn("size-2 shrink-0 rounded-[2px] ring-1 ring-inset", className)}
      aria-hidden
    />
  );
}

/**
 * The band's share of the run as a length: the grid's score bar, reused, so
 * the five tiles read as one distribution rather than five unrelated counts.
 */
function ShareBar({ share, className }: { share: number; className: string }) {
  return (
    <span className="mt-2 block h-1 overflow-hidden rounded-[1px] bg-muted" aria-hidden>
      <span
        className={cn("block h-full origin-left animate-grow rounded-[1px]", className)}
        style={{ width: `${Math.max(0, Math.min(100, share))}%` }}
      />
    </span>
  );
}

export function SummaryTiles({
  run,
  market,
}: {
  run: ScreenerRun;
  market: Market;
}) {
  const total = run.row_count || 0;

  return (
    /*
     * Dividers come from a 1px grid gap over the border colour rather than
     * per-cell borders. At three breakpoints the "which cell is last in its
     * row" arithmetic that per-cell borders need is both unreadable and wrong
     * the moment a column count changes; the gap is correct at every width by
     * construction.
     */
    /*
     * Phone: one swipeable row instead of a 2x3 block. Six tiles stacked three
     * deep cost a full screen before the grid on a 440px phone; in a row they
     * cost one tile's height, snap tile by tile, and the half-visible next tile
     * says there is more.
     */
    <Reveal
      selector="[data-kpi]"
      bounce
      className={cn(
        "panel gap-px overflow-hidden bg-border",
        "max-sm:flex max-sm:snap-x max-sm:snap-mandatory max-sm:overflow-x-auto max-sm:overscroll-x-contain",
        "max-sm:[scrollbar-width:none] max-sm:[&::-webkit-scrollbar]:hidden",
        "max-sm:[&>[data-kpi]]:min-w-[9.75rem] max-sm:[&>[data-kpi]]:shrink-0 max-sm:[&>[data-kpi]]:snap-start",
        "sm:grid sm:grid-cols-3 xl:grid-cols-6",
      )}
    >
      <div data-kpi className="bg-card px-4 py-3">
        <div className="min-w-0">
          <p className="truncate text-[13px] text-muted-foreground">Universe</p>
          <p className="flex items-baseline gap-1.5">
            <CountUp
              locale={market.locale}
              value={total}
              once={`${market.code}:${run.run_date}:row_count`}
              className="numeral text-2xl font-semibold sm:text-4xl"
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
            href={`${marketPath(market.slug)}?rating=${encodeURIComponent(tile.rating)}`}
            data-kpi
            className={cn(
              "press group block bg-card px-4 py-3",
              "hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
            )}
          >
            <div className="min-w-0">
              {/* The label stays sentence-cased at 13px rather than the old
                  uppercase micro-label: at this figure size the caps were
                  competing with the number instead of introducing it. */}
              <p className="flex items-center gap-1.5 truncate text-[13px] text-muted-foreground">
                <Swatch className={tile.rule} />
                {tile.rating}
              </p>
              {/*
                The figure is foreground-coloured, not rating-coloured: the
                swatch and the share bar carry the hue. That is also the only
                readable option: the pale ramp steps as large text on the
                light card measure under 2:1, below the 3:1 large-text floor.
              */}
              <p className="flex items-baseline gap-1.5">
                <CountUp
                  locale={market.locale}
                  value={count}
                  once={`${market.code}:${run.run_date}:${tile.field}`}
                  className="numeral text-2xl font-semibold sm:text-4xl"
                />
              </p>
              <p className="tabular text-[11px] text-muted-foreground">
                {share.toFixed(1)}% of run
              </p>
              <ShareBar share={share} className={tile.fill} />
            </div>
          </Link>
        );
      })}
    </Reveal>
  );
}
