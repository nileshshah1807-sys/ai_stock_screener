import { ArrowDown, ArrowUp, ChevronsDown, ChevronsUp, Minus, Pause } from "lucide-react";

import { cn } from "@/lib/utils";
import { ratingToken } from "@/lib/format";
import { primaryGate } from "@/lib/labels";

/**
 * Rating pill, with gated rows relabelled as an entry state.
 *
 * The five-word ramp -- STRONG BUY / BUY / HOLD / REDUCE / SELL -- is a
 * *merit* vocabulary, and for a gated row it is attached to a *trend*
 * measurement. A name whose gates all fired on price position reads `HOLD`
 * next to a research score of 99.5, and those two are read as arguing with
 * each other even though they answer different questions. The doubt that
 * produces is a correct response to a screen that contradicts itself.
 *
 * So a row whose rating was reduced by a gate is not labelled with a merit
 * word at all. It reads `WAIT` plus the gate that caused it: a statement about
 * timing, which does not compete with the score for the same meaning.
 *
 * Rows that were *not* capped keep the merit word. A stock rated SELL on its
 * own evidence is not waiting for anything, and calling it `WAIT` would be the
 * same category error in the other direction.
 *
 * Accessibility follows `RatingBadge`: the word is always rendered, a glyph
 * encodes the state by shape, and colour is the third signal rather than the
 * first.
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

/**
 * Short gate labels for the chip.
 *
 * `lib/labels.ts` carries the canonical prose, which is written to explain a
 * gate in a tooltip or detail row and is too long to sit inside a pill. These
 * are the same gates named in a few words, and they deliberately describe the
 * *observation* rather than the verdict: "below 200DMA" is checkable against
 * the chart on the same page, "HOLD" is not.
 */
const GATE_CHIP: Record<string, string> = {
  BELOW_MA200: "below 200DMA",
  MA200_TREND: "200DMA falling",
  TREND_BREAKDOWN: "confirmed breakdown",
  WEAK_RELATIVE_STRENGTH: "lagging the market",
  MARKET_REGIME: "market regime",
  LOW_QUALITY: "quality below floor",
  LOW_COVERAGE: "thin coverage",
  LOW_FACTOR_COVERAGE: "thin evidence",
  DATA_ANOMALY: "data anomaly",
  STALE_FUNDAMENTALS: "stale fundamentals",
  STALE_PRICE_BAR: "stale price bar",
  LOW_DATA_QUALITY: "low data quality",
  SPECIALIST_MODEL_REQUIRED: "specialist model",
  ILLIQUID: "illiquid",
};

/** True when a policy gate held this row's rating below its evidence. */
export function ratingWasGated(row: {
  rating_capped?: boolean | null;
  decision_cap_reason?: string | null;
  rating_cap_reason?: string | null;
}): boolean {
  return (
    row.rating_capped === true ||
    Boolean(row.decision_cap_reason) ||
    Boolean(row.rating_cap_reason)
  );
}

/**
 * How far the price sits from clearing its 200-day average, as a sentence.
 *
 * A verdict invites doubt; a distance invites a decision. "2.3% below 200DMA"
 * says exactly what would have to change, and the reader can check it against
 * the chart. Returns null when the gate is not a distance-to-a-line gate, so
 * the caller falls back to the plain label.
 */
export function gateDistance(
  gate: string | null | undefined,
  priceToMa200Pct: number | null | undefined,
): string | null {
  if (gate !== "BELOW_MA200" && gate !== "MA200_TREND") return null;
  if (priceToMa200Pct === null || priceToMa200Pct === undefined) return null;
  if (!Number.isFinite(priceToMa200Pct) || priceToMa200Pct >= 0) return null;
  return `${Math.abs(priceToMa200Pct).toFixed(1)}% below 200DMA`;
}

export function EntryBadge({
  row,
  className,
  size = "sm",
  showReason = true,
}: {
  row: {
    rating: string | null | undefined;
    rating_capped?: boolean | null;
    decision_cap_reason?: string | null;
    rating_cap_reason?: string | null;
    primary_gate?: string | null;
    price_to_ma200_pct?: number | null;
  };
  className?: string;
  size?: "sm" | "md";
  showReason?: boolean;
}) {
  const gated = ratingWasGated(row);
  const shell = cn(
    "inline-flex items-center gap-1 whitespace-nowrap rounded-full font-semibold uppercase tracking-wide ring-1 ring-inset",
    size === "sm" ? "px-1.5 py-0.5 text-[10px]" : "px-2.5 py-1 text-xs",
    className,
  );
  const glyphSize = size === "sm" ? "size-3" : "size-3.5";

  if (!gated) {
    const token = ratingToken(row.rating);
    const Glyph = RATING_GLYPH[token as keyof typeof RATING_GLYPH] ?? Minus;
    return (
      <span className={cn(shell, RATING_STYLES[token] ?? RATING_STYLES.hold)}>
        <Glyph className={glyphSize} aria-hidden />
        {row.rating?.trim() || "—"}
      </span>
    );
  }

  const gate = row.primary_gate?.trim().toUpperCase() ?? "";
  const distance = gateDistance(gate, row.price_to_ma200_pct);
  const reason = distance ?? GATE_CHIP[gate] ?? primaryGate(gate).label.toLowerCase();

  return (
    <span
      className={cn(
        shell,
        "bg-rating-hold text-rating-hold-fg ring-rating-hold-edge",
      )}
    >
      <Pause className={glyphSize} aria-hidden />
      Wait
      {showReason && reason && gate && gate !== "NONE" ? (
        <span className="font-normal normal-case opacity-80">· {reason}</span>
      ) : null}
    </span>
  );
}
