import { cn } from "@/lib/utils";
import { ratingToken } from "@/lib/format";

/**
 * Rating pill.
 *
 * The label text is always rendered, never replaced by a colour swatch: hue
 * alone must not carry the BUY/SELL distinction (WCAG 1.4.1). Colour is a
 * redundant reinforcement of a word that is already there.
 */
const RATING_STYLES: Record<string, string> = {
  "strong-buy":
    "bg-rating-strong-buy/12 text-rating-strong-buy ring-rating-strong-buy/30",
  buy: "bg-rating-buy/12 text-rating-buy ring-rating-buy/30",
  hold: "bg-rating-hold/12 text-rating-hold ring-rating-hold/30",
  reduce: "bg-rating-reduce/12 text-rating-reduce ring-rating-reduce/30",
  sell: "bg-rating-sell/12 text-rating-sell ring-rating-sell/30",
};

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

  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full font-semibold uppercase tracking-wide ring-1 ring-inset",
        size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-xs",
        RATING_STYLES[token] ?? RATING_STYLES.hold,
        className,
      )}
    >
      {label}
    </span>
  );
}
