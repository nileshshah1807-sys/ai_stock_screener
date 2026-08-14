import { cn } from "@/lib/utils";

/**
 * The application mark.
 *
 * Built from the two shapes this interface already uses to represent a score:
 * the gauge arc from the decision-score ring, and the rounded vertical bars
 * from the KPI band and the grid's score meters. The mark is therefore drawn
 * from the product's own vocabulary rather than being a generic chart glyph
 * bolted on -- someone who has used the screener has already seen both halves.
 *
 * The previous mark was lucide's `Terminal`, which said "command line" rather
 * than "equity research" and belonged to the dark-terminal styling this design
 * replaced.
 *
 * Drawn on a 24-unit grid with 2.5-unit strokes and round caps so it holds at
 * the 16px it is actually rendered at. The three bars ascend left to right,
 * which is the one piece of semantics worth carrying at this size.
 */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className={cn("size-full", className)}
      aria-hidden
      focusable="false"
    >
      {/*
        Open gauge arc, matching the decision ring: starts bottom-left, sweeps
        over the top, ends bottom-right. The gap at the bottom is what makes it
        read as a gauge rather than a plain circle.
      */}
      <path
        d="M4.6 18.2a9.5 9.5 0 1 1 14.8 0"
        stroke="currentColor"
        strokeWidth={2.5}
        strokeLinecap="round"
      />
      {/* Three ascending bars, same rounded form as the KPI accent bars. */}
      <path
        d="M8.75 15.5v-2.4"
        stroke="currentColor"
        strokeWidth={2.5}
        strokeLinecap="round"
      />
      <path
        d="M12 15.5v-5"
        stroke="currentColor"
        strokeWidth={2.5}
        strokeLinecap="round"
      />
      <path
        d="M15.25 15.5v-7.6"
        stroke="currentColor"
        strokeWidth={2.5}
        strokeLinecap="round"
      />
    </svg>
  );
}
