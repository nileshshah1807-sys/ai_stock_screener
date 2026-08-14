import { ArrowDown, ArrowUp, ChevronsDown, ChevronsUp, Minus } from "lucide-react";

import { cn } from "@/lib/utils";
import { ratingToken } from "@/lib/format";

/**
 * Rating pill.
 *
 * Solid fill with a darker edge of the same hue. The edge is not decoration:
 * four of the five fills measure between 1.4:1 and 1.8:1 against the light
 * card, so without it a BUY or HOLD pill has no boundary on the surface it
 * sits on.
 *
 * The ramp is a conventional diverging green -> neutral -> red. Green and red
 * at comparable lightness is the single most common colour-vision confusion
 * pair, and this grid exists to separate BUY from SELL, so hue is deliberately
 * the *third* signal here rather than the first:
 *
 *   1. the rating word, always rendered
 *   2. a direction glyph -- double-chevron up, arrow up, dash, arrow down,
 *      double-chevron down -- which encodes position on the scale by shape
 *   3. the fill colour
 *
 * Strip the colour entirely and the scale is still fully readable. That is the
 * property that makes the green/red ramp safe to ship.
 */
const RATING_STYLES: Record<string, string> = {
  "strong-buy":
    "bg-rating-strong-buy text-rating-strong-buy-fg ring-rating-strong-buy-edge",
  buy: "bg-rating-buy text-rating-buy-fg ring-rating-buy-edge",
  hold: "bg-rating-hold text-rating-hold-fg ring-rating-hold-edge",
  reduce: "bg-rating-reduce text-rating-reduce-fg ring-rating-reduce-edge",
  sell: "bg-rating-sell text-rating-sell-fg ring-rating-sell-edge",
};

const RATING_GLYPH = {
  "strong-buy": ChevronsUp,
  buy: ArrowUp,
  hold: Minus,
  reduce: ArrowDown,
  sell: ChevronsDown,
} as const;

export function RatingBadge({
  rating,
  className,
  size = "sm",
}: {
  rating: string | null | undefined;
  className?: string;
  size?: "sm" | "md";
}) {
  const token = ratingToken(rating);
  const label = rating?.trim() || "—";
  const Glyph = RATING_GLYPH[token as keyof typeof RATING_GLYPH] ?? Minus;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full font-semibold uppercase tracking-wide ring-1 ring-inset",
        size === "sm" ? "px-1.5 py-0.5 text-[10px]" : "px-2.5 py-1 text-xs",
        RATING_STYLES[token] ?? RATING_STYLES.hold,
        className,
      )}
    >
      <Glyph className={size === "sm" ? "size-3" : "size-3.5"} aria-hidden />
      {label}
    </span>
  );
}
