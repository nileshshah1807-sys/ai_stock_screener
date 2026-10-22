import { cn } from "@/lib/utils";
import { formatScore, ratingToken } from "@/lib/format";

/**
 * The published decision score: the figure, then the same thin 0-100 bar the
 * screener grid draws under every score, at full width.
 *
 * One bar in both places, so a reader who has learnt the grid's column reads
 * this at a glance. The bar is a gauge -- the track is always the full 0-100
 * scale and the fill is the score -- and the rating boundaries are drawn on
 * the track as 1px gaps and labelled beneath it, because a bare length
 * answers "how big" but not "does this clear BUY", which is the actual
 * question.
 *
 * Colour comes from the rating ramp, and the rating word is carried by the
 * badge beside the page title and the caption here. Hue is never the only
 * carrier: the number, the bar length and the word all say the same thing.
 */

/** Rating band lower bounds, matching the finalizer's mapping. */
const THRESHOLDS = [40, 50, 60, 70];

export function DecisionScore({
  score,
  rating,
  caption,
  className,
}: {
  score: number | null | undefined;
  rating: string | null | undefined;
  caption?: string;
  className?: string;
}) {
  const token = ratingToken(rating);
  const hasScore = typeof score === "number" && Number.isFinite(score);
  const clamped = hasScore ? Math.max(0, Math.min(100, score)) : 0;

  return (
    <figure
      className={cn("m-0 flex flex-col gap-3", className)}
      role="img"
      aria-label={
        hasScore
          ? `Decision score ${formatScore(clamped)} out of 100, rated ${rating ?? "unrated"}.`
          : "Decision score unavailable."
      }
    >
      {/*
        The figure is deliberately NOT rating-coloured: the pale steps of the
        ramp measure under 2:1 on the card, below the large-text floor. The
        bar carries the hue.
      */}
      <p className="flex items-baseline gap-1.5" aria-hidden>
        <span className="numeral text-display text-foreground">
          {hasScore ? formatScore(clamped) : "—"}
        </span>
        <span className="text-xs text-muted-foreground">/ 100</span>
      </p>

      <div aria-hidden>
        <div className="relative h-2 overflow-hidden rounded-[2px] bg-muted">
          {hasScore ? (
            <div
              className="absolute inset-y-0 left-0 origin-left animate-grow rounded-[2px]"
              style={{
                width: `${clamped}%`,
                // HOLD's fill is the ramp's palest step and all but vanishes
                // on the muted track; its edge tone is the same band.
                background: `var(--rating-${token}${token === "hold" ? "-edge" : ""})`,
              }}
            />
          ) : null}
          {/* Band boundaries, cut through track and fill alike so the reader
              can see which side of BUY the score lands on. */}
          {THRESHOLDS.map((threshold) => (
            <span
              key={threshold}
              className="absolute inset-y-0 w-px bg-card"
              style={{ left: `${threshold}%` }}
            />
          ))}
        </div>
        <div className="tabular relative mt-1 h-4 text-[11px] text-muted-foreground">
          {THRESHOLDS.map((threshold) => (
            <span
              key={threshold}
              className="absolute -translate-x-1/2"
              style={{ left: `${threshold}%` }}
            >
              {threshold}
            </span>
          ))}
        </div>
      </div>

      {caption ? (
        <figcaption className="text-xs leading-relaxed text-muted-foreground">
          {caption}
        </figcaption>
      ) : null}
    </figure>
  );
}
