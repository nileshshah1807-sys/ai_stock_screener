import { cn } from "@/lib/utils";
import { MISSING } from "@/lib/format";
import { eligibilityClass, marketRegime, primaryGate } from "@/lib/labels";
import { FACTOR_BLOCKS, type SnapshotRow } from "@/lib/types";

/**
 * Model 5.0 factor breakdown.
 *
 * Shows each block's contribution to the blend alongside its percentile and
 * how much of it was actually observed. The three are deliberately kept
 * distinct: a block can score well on thin evidence, and the coverage figure is
 * the only thing that says so. The published research score is the percentile
 * of the blend, not the blend itself, so both are shown -- otherwise the
 * weighted contributions visibly fail to add up to the headline number.
 */
export function FactorBlocks({ row }: { row: SnapshotRow }) {
  if (!row.factor_model_applied) return null;

  const blocks = FACTOR_BLOCKS.map((block) => {
    const score = row[`${block.key}_score` as keyof SnapshotRow] as
      | number
      | null;
    const percentile = row[`${block.key}_percentile` as keyof SnapshotRow] as
      | number
      | null;
    const coverage = row[`${block.key}_coverage` as keyof SnapshotRow] as
      | number
      | null;
    return { ...block, score, percentile, coverage };
  });

  return (
    <div className="space-y-4">
      <ul className="space-y-2.5">
        {blocks.map((block) => {
          const thin = block.coverage !== null && block.coverage < 0.5;
          return (
            <li key={block.key} className="space-y-1">
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <span className="font-medium">
                  {block.label}
                  <span className="ml-1.5 text-xs text-muted-foreground">
                    {Math.round(block.weight * 100)}%
                  </span>
                </span>
                <span className="tabular font-mono text-xs">
                  {block.score === null ? (
                    <span className="text-muted-foreground">{MISSING}</span>
                  ) : (
                    <>
                      {block.score.toFixed(1)}
                      {block.percentile !== null && (
                        <span
                          className={cn(
                            "ml-2",
                            block.percentile >= 70
                              ? "text-positive"
                              : block.percentile < 30
                                ? "text-negative"
                                : "text-muted-foreground",
                          )}
                        >
                          P{Math.round(block.percentile)}
                        </span>
                      )}
                    </>
                  )}
                </span>
              </div>

              {/* The bar encodes the block score; width alone is never the only
                  signal, since the number sits directly above it. */}
              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  className={cn(
                    "h-full rounded-full",
                    thin ? "bg-muted-foreground/40" : "bg-primary",
                  )}
                  style={{ width: `${Math.max(0, Math.min(100, block.score ?? 0))}%` }}
                />
              </div>

              <p className="text-[11px] text-muted-foreground">
                Coverage{" "}
                {block.coverage === null
                  ? MISSING
                  : `${Math.round(block.coverage * 100)}%`}
                {thin
                  ? " — too thin to be treated as evidence; the block is shrunk toward neutral 50."
                  : ""}
              </p>
            </li>
          );
        })}
      </ul>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 border-t pt-3 text-sm">
        <div>
          <dt className="text-xs text-muted-foreground">Research score</dt>
          <dd className="tabular font-mono">
            {row.research_score?.toFixed(2) ?? MISSING}
            {row.research_score_raw !== null && (
              <span className="ml-2 text-xs text-muted-foreground">
                blend {row.research_score_raw.toFixed(2)}
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Eligibility</dt>
          <dd title={eligibilityClass(row.eligibility_class).meaning}>
            {eligibilityClass(row.eligibility_class).label}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Binding gate</dt>
          <dd title={primaryGate(row.primary_gate).meaning}>
            {primaryGate(row.primary_gate).label}
            {row.gate_severity ? (
              <span className="ml-1.5 text-xs text-muted-foreground">
                +{row.gate_severity - 1} more
              </span>
            ) : null}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Market regime</dt>
          <dd title={marketRegime(row.market_regime).meaning}>
            {marketRegime(row.market_regime).label}
          </dd>
        </div>
      </dl>

      {row.value_quality_cap_applied ? (
        <p className="rounded border border-caution/40 bg-caution/10 p-2 text-[11px] leading-snug">
          Value was capped at 50 because quality sits in the bottom{" "}
          {Math.round(30)}% of the cross-section — the classic value trap. The
          uncapped value score was{" "}
          <span className="tabular font-mono">
            {row.value_score_uncapped?.toFixed(1) ?? MISSING}
          </span>
          .
        </p>
      ) : null}

      <p className="text-[11px] leading-snug text-muted-foreground">
        The published research score is the percentile of the weighted blend
        across this run&apos;s universe, so it will not equal the weighted sum
        above. Ratings are therefore relative to the cross-section; the absolute
        protections are the trend, coverage and liquidity gates and the regime
        overlay.
      </p>
    </div>
  );
}
