import { TriangleAlert } from "lucide-react";

import { formatPercent } from "@/lib/format";

const MISSING = "—";

/**
 * What the market prices, next to what the model scored.
 *
 * Every input the factor model reads is backward-looking: a closed fiscal year,
 * a three-year CAGR, a filed balance sheet. The price is a claim about what
 * gets filed next. When the two disagree the score cannot say so, because the
 * disagreement lives entirely on the side it cannot see.
 *
 * This panel is the counter-argument the score cannot carry. On 2026-08-24
 * LUPIN read 99.45 at rank 14 while its forward PE (21.40) sat *above* its
 * trailing PE (18.13) -- consensus pricing a 15.3% earnings decline against the
 * trailing EPS the score was computed on.
 *
 * None of it is scored. `Forward_PE` is analyst consensus, present for 45% of
 * the universe and skewed 19x by market cap, so feeding it to the model would
 * re-sort the screen by analyst attention. Shown here it costs nothing and
 * says the one thing the ranking cannot.
 *
 * The panel renders only when at least one of the three signals exists. An
 * empty panel on a row with no forward coverage would read as reassurance, and
 * "no analyst covers this" is not the same as "no expected decline".
 */
export type ExpectationsData = {
  status: string;
  warning: string;
  forwardEps: number | null;
  changePct: number | null;
  trailingEps: number | null;
  impliedGrowthPct: number | null;
  assumedGrowthPct: number | null;
  growthGapPct: number | null;
  guidanceTransition: string;
  guidanceDowngraded: boolean;
};

function Fact({
  label,
  value,
  detail,
  tone = "",
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: string;
}) {
  return (
    <div className="bg-muted/40 px-4 py-3">
      <dt className="text-[11px] uppercase tracking-wider text-muted-foreground">
        {label}
      </dt>
      <dd className={`tabular mt-0.5 text-sm font-semibold ${tone}`}>{value}</dd>
      {detail ? (
        <dd className="mt-0.5 text-[11px] text-muted-foreground">{detail}</dd>
      ) : null}
    </div>
  );
}

export function ExpectationsGap({ data }: { data: ExpectationsData }) {
  const hasEarnings = data.changePct !== null;
  const hasGrowth = data.growthGapPct !== null;
  const hasGuidance = Boolean(data.guidanceTransition);

  if (!hasEarnings && !hasGrowth && !hasGuidance && !data.warning) return null;

  return (
    <section className="panel p-5 sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-heading font-semibold">Market expectations</h2>
        <p className="text-[11px] text-muted-foreground">
          Not scored — the model reads filed history only
        </p>
      </div>

      {data.warning ? (
        <p className="mt-3 flex items-start gap-2 rounded-row bg-caution/10 px-3 py-2 text-xs text-caution ring-1 ring-inset ring-caution/25">
          <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
          <span className="text-foreground/90">{data.warning}</span>
        </p>
      ) : null}

      <dl className="mt-4 grid grid-cols-1 gap-px overflow-hidden rounded-row bg-border sm:grid-cols-3">
        <Fact
          label="Expected earnings"
          value={
            hasEarnings
              ? formatPercent(data.changePct, 1, true)
              : data.status.startsWith("Priced")
                ? data.status
                : MISSING
          }
          detail={
            hasEarnings && data.trailingEps !== null && data.forwardEps !== null
              ? `Trailing ₹${data.trailingEps.toFixed(2)} → forward ₹${data.forwardEps.toFixed(2)}`
              : data.status
          }
          tone={
            !hasEarnings
              ? ""
              : data.changePct! >= 0
                ? "text-positive"
                : "text-negative"
          }
        />
        <Fact
          label="Growth priced in"
          value={
            hasGrowth && data.impliedGrowthPct !== null
              ? `${data.impliedGrowthPct.toFixed(1)}%`
              : MISSING
          }
          detail={
            hasGrowth && data.assumedGrowthPct !== null
              ? `DCF assumed ${data.assumedGrowthPct.toFixed(1)}% — a ${data.growthGapPct! >= 0 ? "surplus" : "shortfall"} of ${Math.abs(data.growthGapPct!).toFixed(1)} pts`
              : "No usable reverse-DCF solve"
          }
          tone={
            !hasGrowth ? "" : data.growthGapPct! >= 0 ? "text-positive" : ""
          }
        />
        <Fact
          label="Guidance"
          value={hasGuidance ? data.guidanceTransition : MISSING}
          detail={
            hasGuidance
              ? data.guidanceDowngraded
                ? "Weaker than the prior call"
                : "No step down from the prior call"
              : "No current-cycle call to compare"
          }
          tone={data.guidanceDowngraded ? "text-negative" : ""}
        />
      </dl>
    </section>
  );
}
