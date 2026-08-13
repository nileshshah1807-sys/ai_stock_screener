import Link from "next/link";

import { RatingBadge } from "@/components/rating-badge";
import {
  CappedChip,
  CoverageCell,
  RedFlagChip,
  TranscriptChip,
} from "@/components/evidence-chips";
import { PlainHeader, SortHeader } from "@/components/screener/sort-header";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { dcfStatus, primaryGate } from "@/lib/labels";
import {
  formatINR,
  formatINRCompact,
  formatNumber,
  formatPercent,
  formatRatioAsPercent,
  formatScore,
  MISSING,
} from "@/lib/format";
import type { SnapshotRow } from "@/lib/types";

/**
 * Signed change cell. Sign is carried by an explicit +/- and by position, so
 * colour is reinforcement rather than the only signal.
 */
function ChangeCell({ value }: { value: number | null }) {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground">{MISSING}</span>;
  }
  return (
    <span
      className={cn(
        "tabular",
        value > 0 ? "text-positive" : value < 0 ? "text-negative" : "",
      )}
    >
      {formatPercent(value, 1, true)}
    </span>
  );
}

/**
 * Decision score with its evidence score behind it.
 *
 * When a ceiling has been applied the two differ, and showing only the final
 * number would hide the single most important fact about the row: that the
 * model wanted to score it higher but a gate stopped it.
 */
function ScoreCell({ row }: { row: SnapshotRow }) {
  const decision = row.decision_score ?? row.final_score;
  const evidence = row.evidence_score;
  const capped =
    evidence !== null &&
    decision !== null &&
    Math.abs(evidence - decision) > 0.05;

  if (!capped) {
    return (
      <span className="tabular font-mono text-sm font-semibold">
        {formatScore(decision)}
      </span>
    );
  }

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span className="tabular cursor-help font-mono text-sm font-semibold" />
        }
      >
        {formatScore(decision)}
        <span className="ml-1 text-[10px] font-normal text-caution">
          ▼{formatScore(evidence)}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-72">
        <p className="font-medium">Decision score capped</p>
        <p className="text-xs opacity-90">
          Evidence scored {formatScore(evidence)}; a policy ceiling reduced the
          published decision to {formatScore(decision)}.
        </p>
        {row.decision_cap_reason || row.rating_cap_reason ? (
          <p className="mt-1 text-xs opacity-90">
            {row.decision_cap_reason || row.rating_cap_reason}
          </p>
        ) : null}
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * A factor percentile, shown as a rank within the cross-section.
 *
 * Rendered as "P72" rather than a bare 72 because these are percentiles, not
 * scores on the same 0-100 scale as Decision. Conflating the two would invite
 * reading a quality percentile as if it were a rating band.
 */
function PercentileCell({ value }: { value: number | null }) {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground">{MISSING}</span>;
  }
  return (
    <span
      className={cn(
        "tabular font-mono text-xs",
        value >= 70 ? "text-positive" : value < 30 ? "text-negative" : "",
      )}
    >
      P{Math.round(value)}
    </span>
  );
}

/** The binding reason a row is not rated higher. */
function GateChip({ gate }: { gate: string | null }) {
  if (!gate || gate === "NONE") {
    return <span className="text-muted-foreground">{MISSING}</span>;
  }
  const { label, meaning } = primaryGate(gate);
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span className="cursor-help rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium" />
        }
      >
        {label}
      </TooltipTrigger>
      <TooltipContent className="max-w-72">
        <p className="font-medium">{label}</p>
        <p className="text-xs opacity-90">{meaning}</p>
      </TooltipContent>
    </Tooltip>
  );
}

export function ScreenerTable({
  rows,
  params,
  sort,
  dir,
}: {
  rows: SnapshotRow[];
  params: URLSearchParams;
  sort: string;
  dir: "asc" | "desc";
}) {
  const headerProps = { currentSort: sort, currentDir: dir, params };
  // A run is either 4.x or Model 5.0 for its whole cross-section, so one row
  // settles it. Showing both column sets would double the grid width and leave
  // whichever model did not run as a full column of dashes.
  const factorModel = rows.some((row) => row.factor_model_applied === true);

  if (!rows.length) {
    return (
      <div className="rounded-lg border bg-card py-16 text-center">
        <p className="text-sm font-medium">No stocks match these filters</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Try widening the rating selection or clearing the evidence filters.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      {/* The grid is wider than a phone and legitimately so: it is a
          cross-sectional comparison. It scrolls inside its own container so
          the page body never scrolls sideways. */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">
            Screened NSE stocks ordered by {sort.replace(/_/g, " ")}, showing
            model decision score, evidence coverage, and execution suitability.
          </caption>
          <thead className="sticky-head">
            <tr>
              <SortHeader
                {...headerProps}
                label="#"
                column="investment_rank"
                numeric
                defaultDir="asc"
                className="w-12"
                title="Investment Rank: decision score first, then evidence. The primary rank."
              />
              <PlainHeader label="Stock" className="sticky-col min-w-44" />
              <PlainHeader label="Rating" />
              <SortHeader
                {...headerProps}
                label="Decision"
                column="decision_score"
                numeric
                title="Decision Score: evidence score after all coverage, quality, anomaly, and trend ceilings."
              />
              {factorModel ? (
                <>
                  <SortHeader
                    {...headerProps}
                    label="Qual"
                    column="quality_percentile"
                    numeric
                    title="Quality percentile: ROIC, cash generation, accruals, leverage and stability, ranked within sector. BUY needs 40, STRONG BUY 70."
                  />
                  <SortHeader
                    {...headerProps}
                    label="Mom"
                    column="momentum_percentile"
                    numeric
                    title="Momentum percentile: risk-adjusted 12-1 and 6-1 returns plus relative strength. STRONG BUY needs 70."
                  />
                  <SortHeader
                    {...headerProps}
                    label="Grow"
                    column="growth_percentile"
                    numeric
                    title="Growth percentile: multi-year CAGR, acceleration, margin direction and cash confirmation. STRONG BUY needs 60."
                  />
                </>
              ) : (
                <>
                  <SortHeader
                    {...headerProps}
                    label="Fund"
                    column="fundamental_score"
                    numeric
                  />
                  <SortHeader
                    {...headerProps}
                    label="Tech"
                    column="technical_score"
                    numeric
                  />
                </>
              )}
              <PlainHeader
                label="Cov F/T"
                numeric
                title="Fundamental coverage as a share of the fields the selected sector model expects, and technical score coverage."
              />
              <SortHeader
                {...headerProps}
                label="DCF"
                column="dcf_base_case_upside"
                numeric
                title="Reverse-DCF base-case upside. Evidence only; not a target price."
              />
              {factorModel && (
                <SortHeader
                  {...headerProps}
                  label="Gate"
                  column="gate_severity"
                  defaultDir="asc"
                  title="The most severe reason this row is not rated higher. A BUY-eligible row can still show a STRONG BUY gate here."
                />
              )}
              <PlainHeader label="Evidence" title="Transcript, red-flag, and rating-cap indicators" />
              <SortHeader
                {...headerProps}
                label="Price"
                column="current_price"
                numeric
              />
              <SortHeader
                {...headerProps}
                label="1M"
                column="pct_change_1m"
                numeric
              />
              <SortHeader
                {...headerProps}
                label="Mkt cap"
                column="market_cap"
                numeric
              />
              <SortHeader {...headerProps} label="PE" column="pe_ratio" numeric />
              <PlainHeader
                label="Liq"
                title="Execution overlay. Never changes the score or rating."
              />
            </tr>
          </thead>

          <tbody>
            {rows.map((row) => (
              <tr
                key={row.symbol}
                className="border-t transition-colors hover:bg-muted/40"
              >
                <td className="tabular px-2 py-1.5 text-right font-mono text-xs text-muted-foreground">
                  {row.investment_rank ?? MISSING}
                </td>

                <td className="sticky-col px-2 py-1.5">
                  <Link
                    href={`/stocks/${row.symbol}`}
                    className="block rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="block font-mono text-xs font-semibold">
                      {row.symbol}
                    </span>
                    <span className="block max-w-52 truncate text-[11px] text-muted-foreground">
                      {row.company ?? MISSING}
                    </span>
                  </Link>
                </td>

                <td className="px-2 py-1.5">
                  <RatingBadge rating={row.rating} />
                </td>

                <td className="px-2 py-1.5 text-right">
                  <ScoreCell row={row} />
                </td>

                {factorModel ? (
                  <>
                    <td className="px-2 py-1.5 text-right">
                      <PercentileCell value={row.quality_percentile} />
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      <PercentileCell value={row.momentum_percentile} />
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      <PercentileCell value={row.growth_percentile} />
                    </td>
                  </>
                ) : (
                  <>
                    <td className="tabular px-2 py-1.5 text-right font-mono text-xs">
                      {formatScore(row.fundamental_score)}
                    </td>
                    <td className="tabular px-2 py-1.5 text-right font-mono text-xs">
                      {formatScore(row.technical_score)}
                    </td>
                  </>
                )}

                <td className="px-2 py-1.5 text-right">
                  <CoverageCell
                    fundamental={row.fundamental_coverage}
                    technical={row.technical_coverage}
                  />
                </td>

                <td className="tabular px-2 py-1.5 text-right font-mono text-xs">
                  {row.dcf_status && row.dcf_base_case_upside !== null ? (
                    <ChangeCell value={(row.dcf_base_case_upside ?? 0) * 100} />
                  ) : (
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <span className="cursor-help text-muted-foreground" />
                        }
                      >
                        {MISSING}
                      </TooltipTrigger>
                      <TooltipContent className="max-w-72">
                        <p className="font-medium">
                          {dcfStatus(row.dcf_status).label}
                        </p>
                        <p className="text-xs opacity-90">
                          {dcfStatus(row.dcf_status).meaning ||
                            "No usable DCF result. Treated as neutral evidence, not as a negative signal."}
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  )}
                </td>

                {factorModel && (
                  <td className="px-2 py-1.5">
                    <GateChip gate={row.primary_gate} />
                  </td>
                )}

                <td className="px-2 py-1.5">
                  <span className="flex items-center gap-1.5">
                    <TranscriptChip
                      status={row.transcript_status}
                      eligible={row.transcript_scoring_eligible}
                      guidance={row.transcript_guidance}
                    />
                    <RedFlagChip
                      status={row.red_flag_status}
                      severity={row.red_flag_severity}
                      wouldChange={row.shadow_red_flag_would_change}
                    />
                    <CappedChip
                      capped={row.rating_capped}
                      reason={row.rating_cap_reason ?? row.decision_cap_reason}
                    />
                  </span>
                </td>

                <td className="tabular px-2 py-1.5 text-right font-mono text-xs">
                  {formatINR(row.current_price, 0)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono text-xs">
                  <ChangeCell value={row.pct_change_1m} />
                </td>
                <td className="tabular px-2 py-1.5 text-right font-mono text-xs">
                  {formatINRCompact(row.market_cap)}
                </td>
                <td className="tabular px-2 py-1.5 text-right font-mono text-xs">
                  {formatNumber(row.pe_ratio, 1)}
                </td>

                <td className="px-2 py-1.5">
                  {row.liquidity_grade ? (
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <span
                            className={cn(
                              "tabular cursor-help font-mono text-xs",
                              row.portfolio_actionable
                                ? "text-foreground"
                                : "text-caution",
                            )}
                          />
                        }
                      >
                        {row.liquidity_grade}
                      </TooltipTrigger>
                      <TooltipContent className="max-w-64">
                        <p className="text-xs">
                          {row.portfolio_actionable
                            ? "The configured target position is executable at the assumed participation rate."
                            : "Not executable at the configured target position. This does not change the score or rating."}
                        </p>
                        <p className="mt-1 text-xs opacity-80">
                          20-day median turnover{" "}
                          {formatINRCompact(row.median_turnover_20d_inr)}
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  ) : (
                    <span className="text-xs text-muted-foreground">
                      {MISSING}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
