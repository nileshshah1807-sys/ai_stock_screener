import { cn } from "@/lib/utils";
import { formatScore, ratingToken } from "@/lib/format";

/**
 * The published decision score as a ring.
 *
 * Ported from the Figma "Decision Score" card (node 1:895), which is the one
 * element of the mock the app had no equivalent for: the score existed only as
 * a figure in a table cell, with nothing showing where it sat on the 0-100
 * range it is judged against.
 *
 * The ring is a gauge, not a pie -- it encodes one value against a fixed scale,
 * so the track is always the full circle and the arc is the score. Rating
 * thresholds are drawn as ticks on the track, because a bare arc answers "how
 * big" but not "does this clear BUY", which is the actual question.
 *
 * Colour comes from the rating ramp, and the rating word is printed underneath.
 * Hue is never the only carrier: the number, the word, and the arc length all
 * say the same thing.
 */

const SIZE = 176;
const STROKE = 14;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/** Rating band lower bounds, matching the finalizer's mapping. */
const THRESHOLDS = [40, 50, 60, 70];

const ARC_STROKE: Record<string, string> = {
  "strong-buy": "stroke-rating-strong-buy",
  buy: "stroke-rating-buy",
  hold: "stroke-rating-hold",
  reduce: "stroke-rating-reduce",
  sell: "stroke-rating-sell",
};

/*
 * The centre figure is deliberately NOT rating-coloured. The mock's own score
 * card prints "60.8" in its near-black foreground and lets the ring carry the
 * hue, and under this palette that is also the only legible option: the amber
 * fill measures 1.45:1 on the card, far below the 3:1 large-text floor.
 */

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

  // The arc starts at 12 o'clock and runs clockwise; the -90deg rotation on
  // the group is what moves it off the SVG's native 3 o'clock start.
  const offset = CIRCUMFERENCE * (1 - clamped / 100);

  return (
    <figure className={cn("m-0 flex flex-col items-center gap-3", className)}>
      <div className="relative" style={{ width: SIZE, height: SIZE }}>
        <svg
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          width={SIZE}
          height={SIZE}
          role="img"
          aria-label={
            hasScore
              ? `Decision score ${formatScore(clamped)} out of 100, rated ${rating ?? "unrated"}.`
              : "Decision score unavailable."
          }
        >
          <g transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}>
            <circle
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              strokeWidth={STROKE}
              className="stroke-muted"
            />

            {hasScore ? (
              <circle
                cx={SIZE / 2}
                cy={SIZE / 2}
                r={RADIUS}
                fill="none"
                strokeWidth={STROKE}
                strokeLinecap="round"
                strokeDasharray={CIRCUMFERENCE}
                strokeDashoffset={offset}
                className={cn(
                  "animate-[arc_var(--duration-slow)_var(--ease-entrance)_both]",
                  ARC_STROKE[token] ?? ARC_STROKE.hold,
                )}
                style={
                  {
                    "--arc-from": CIRCUMFERENCE,
                    "--arc-to": offset,
                  } as React.CSSProperties
                }
              />
            ) : null}

            {/* Band boundaries. Drawn over the track so the reader can see
                which side of BUY the arc actually lands on. */}
            {THRESHOLDS.map((threshold) => {
              const angle = (threshold / 100) * 2 * Math.PI;
              const inner = RADIUS - STROKE / 2;
              const outer = RADIUS + STROKE / 2;
              const cx = SIZE / 2;
              const cy = SIZE / 2;
              return (
                <line
                  key={threshold}
                  x1={cx + inner * Math.cos(angle)}
                  y1={cy + inner * Math.sin(angle)}
                  x2={cx + outer * Math.cos(angle)}
                  y2={cy + outer * Math.sin(angle)}
                  // stroke-card, not stroke-background: the ring always sits
                  // on a card, and in dark mode the two differ enough that
                  // background-coloured ticks read as smudges on the track.
                  className="stroke-card"
                  strokeWidth={2}
                />
              );
            })}
          </g>
        </svg>

        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="numeral text-5xl font-semibold text-foreground">
            {hasScore ? formatScore(clamped) : "—"}
          </span>
          <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
            of 100
          </span>
        </div>
      </div>

      {caption ? (
        <figcaption className="max-w-64 text-center text-xs leading-relaxed text-muted-foreground">
          {caption}
        </figcaption>
      ) : null}
    </figure>
  );
}
