import { formatScore, ratingToken } from "@/lib/format";
import { dcfStatus } from "@/lib/labels";
import { researchScoreMode } from "@/lib/model-display.mjs";
import type { SnapshotRowWithPayload } from "@/lib/types";

/**
 * The active run's score chain as a waterfall.
 *
 * The finalizer computes one sequence after choosing the model's starting
 * score. In 4.x that start is the fundamental/technical core; in Model 5.0 it
 * is the factor research score (with reverse DCF already inside Value).
 *
 *   Starting score = v4 core OR Model 5.0 research score
 *   After DCF     = Core + w_dcf * (DCF_Valuation_Score - 50)
 *   Evidence      = After DCF + w_tx * min(Transcript_Effective - 50, 0)
 *   Decision      = min(Evidence, applicable policy ceiling)
 *
 * A waterfall is the right form because the question is "how did we get from
 * the core score to the published one", which is a sequence of signed
 * contributions against a running total -- not five independent magnitudes.
 * An ineligible stage contributes exactly zero and is drawn as a flat marker
 * rather than omitted, so "this evidence existed but did not count" stays
 * visible instead of being silently absent.
 */

type Stage = {
  key: string;
  label: string;
  from: number;
  to: number;
  kind: "base" | "delta" | "cap" | "total";
  note: string;
};

function num(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function buildStages(row: SnapshotRowWithPayload): Stage[] {
  const payload = row.payload ?? {};
  const factorModel = row.factor_model_applied === true;
  const scoreMode = researchScoreMode(row.research_score_basis);

  const core = row.combined_score ?? num(payload.Combined_Score) ?? 0;
  const rawResearch =
    row.research_score_raw ?? num(payload.Research_Score_Raw);
  const afterDcf = row.score_after_dcf ?? num(payload.Score_After_DCF) ?? core;
  const evidence = row.evidence_score ?? num(payload.Evidence_Score) ?? afterDcf;
  const decision =
    row.decision_score ?? num(payload.Decision_Score) ?? row.final_score ?? evidence;

  const dcfEligible = row.dcf_blend_eligible ?? false;
  const transcriptEligible = row.transcript_scoring_eligible ?? false;
  const dcf = dcfStatus(row.dcf_status);
  const coreNote = factorModel
    ? scoreMode === "percentile"
      ? `Cross-sectional percentile ${formatScore(core)} of the weighted factor blend ${formatScore(rawResearch)}.`
      : scoreMode === "weighted"
        ? `Weighted factor blend ${formatScore(rawResearch ?? core)} published directly as the research score.`
        : `Factor research score ${formatScore(core)}; this row does not identify whether the weighted blend was percentile-ranked.`
    : `0.70 × fundamental ${formatScore(row.fundamental_score)} + 0.30 × technical ${formatScore(row.technical_score)}`;

  const stages: Stage[] = [
    {
      key: "core",
      label: factorModel ? "Research" : "Core",
      from: 0,
      to: core,
      kind: "base",
      note: coreNote,
    },
    {
      key: "dcf",
      label: "Reverse DCF",
      from: core,
      to: afterDcf,
      kind: "delta",
      note: factorModel
        ? dcfEligible
          ? `${dcf.label}: valuation evidence is included once inside the Value block; no second post-research adjustment is applied.`
          : `${dcf.label}. No separate post-research adjustment is applied.`
        : dcfEligible
          ? `${dcf.label}: valuation score ${formatScore(row.dcf_valuation_score)} applied at the configured weight.`
          : `${dcf.label}. ${dcf.meaning || "Contributes zero, neither reward nor penalty."}`,
    },
    {
      key: "transcript",
      label: "Transcript",
      from: afterDcf,
      to: evidence,
      kind: "delta",
      note: transcriptEligible
        ? `${row.transcript_status}: downside-only, so this stage can subtract but never add.`
        : `${row.transcript_status ?? "No transcript"}. Contributes zero and does not cap the rating.`,
    },
    {
      key: "ceiling",
      label: "Policy ceiling",
      from: evidence,
      to: decision,
      kind: "cap",
      note:
        Math.abs(evidence - decision) > 0.05
          ? (row.decision_cap_reason ??
            row.rating_cap_reason ??
            "A policy ceiling reduced the decision score.")
          : "No ceiling applied.",
    },
    {
      key: "decision",
      label: "Decision",
      from: 0,
      to: decision,
      kind: "total",
      note: `Maps mechanically to ${row.rating ?? "—"}: STRONG BUY 70+, BUY 60-69.99, HOLD 50-59.99, REDUCE 40-49.99, SELL below 40.`,
    },
  ];

  return stages;
}

const ROW_HEIGHT = 34;
const BAR_HEIGHT = 18;
const LABEL_WIDTH = 104;
const VALUE_WIDTH = 92;
const PLOT_WIDTH = 320;
const AXIS_MAX = 100;

export function ScoreWaterfall({ row }: { row: SnapshotRowWithPayload }) {
  const stages = buildStages(row);
  const height = stages.length * ROW_HEIGHT + 26;
  const width = LABEL_WIDTH + PLOT_WIDTH + VALUE_WIDTH;

  const x = (value: number) =>
    LABEL_WIDTH + (Math.max(0, Math.min(AXIS_MAX, value)) / AXIS_MAX) * PLOT_WIDTH;

  // Rating thresholds, drawn as reference lines so a score reads against the
  // boundary it is actually judged by rather than against an empty axis.
  const thresholds = [
    { value: 40, label: "40" },
    { value: 50, label: "50" },
    { value: 60, label: "60" },
    { value: 70, label: "70" },
  ];

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ maxHeight: height * 1.4 }}
        role="img"
        aria-label={`Score waterfall: starting score ${formatScore(stages[0].to)}, decision ${formatScore(stages[4].to)}.`}
      >
        {thresholds.map((threshold) => (
          <g key={threshold.value}>
            <line
              x1={x(threshold.value)}
              y1={4}
              x2={x(threshold.value)}
              y2={height - 22}
              stroke="var(--border)"
              strokeWidth={1}
              strokeDasharray="2 3"
            />
            <text
              x={x(threshold.value)}
              y={height - 8}
              textAnchor="middle"
              className="fill-muted-foreground"
              style={{ fontSize: 9, fontFamily: "var(--font-mono)" }}
            >
              {threshold.label}
            </text>
          </g>
        ))}

        {stages.map((stage, index) => {
          const y = index * ROW_HEIGHT + 6;
          const low = Math.min(stage.from, stage.to);
          const high = Math.max(stage.from, stage.to);
          const delta = stage.to - stage.from;
          const isFlat = Math.abs(delta) < 0.05;

          /*
           * The starting bar is the neutral primary; the published total is
           * filled with this row's own rating colour, so the bar the eye lands
           * on is the same colour as the badge at the top of the page and the
           * ring beside it. A fixed accent was wrong here -- with the chart
           * ramp now drawn from the rating scale, any constant choice paints
           * some rows' final score in another band's colour.
           *
           * Intermediate deltas keep the directional positive/negative pair
           * rather than a rating hue: they are signed adjustments, not
           * ratings, and borrowing the rating ramp would imply a
           * classification the stage does not carry.
           */
          const fill =
            stage.kind === "base"
              ? "var(--primary)"
              : stage.kind === "total"
                ? `var(--rating-${ratingToken(row.rating)})`
                : delta > 0
                  ? "var(--positive)"
                  : delta < 0
                    ? "var(--negative)"
                    : "var(--muted-foreground)";

          const barX = x(low);
          const barWidth = Math.max(x(high) - x(low), isFlat ? 2 : 3);

          return (
            <g key={stage.key}>
              <text
                x={LABEL_WIDTH - 8}
                y={y + BAR_HEIGHT / 2 + 4}
                textAnchor="end"
                className="fill-foreground"
                style={{ fontSize: 11 }}
              >
                {stage.label}
              </text>

              {/* Connector from the previous running total, so the eye follows
                  the sequence rather than reading five separate bars. */}
              {index > 0 && index < stages.length - 1 ? (
                <line
                  x1={x(stage.from)}
                  y1={y - ROW_HEIGHT + BAR_HEIGHT + 6}
                  x2={x(stage.from)}
                  y2={y}
                  stroke="var(--border)"
                  strokeWidth={1}
                />
              ) : null}

              {/* Each bar draws in 60ms after the one above it, so the eye
                  follows the sequence in the order the finalizer actually
                  applies it rather than meeting five finished bars at once. */}
              <rect
                x={barX}
                y={y}
                width={barWidth}
                height={BAR_HEIGHT}
                rx={3}
                fill={fill}
                opacity={isFlat ? 0.45 : 1}
                className="bar-grow"
                style={{ "--i": index } as React.CSSProperties}
              />

              <text
                x={LABEL_WIDTH + PLOT_WIDTH + 8}
                y={y + BAR_HEIGHT / 2 + 4}
                className="fill-foreground"
                style={{ fontSize: 11, fontFamily: "var(--font-mono)" }}
              >
                {stage.kind === "base" || stage.kind === "total"
                  ? formatScore(stage.to)
                  : isFlat
                    ? "0.0"
                    : `${delta > 0 ? "+" : ""}${delta.toFixed(1)}`}
              </text>
            </g>
          );
        })}
      </svg>

      {/* The table view is the accessible equivalent of the graphic and also
          the place the reasoning lives -- an SVG cannot carry why a stage was
          skipped. */}
      <figcaption className="mt-3 space-y-1.5">
        {stages.map((stage) => (
          <div key={stage.key} className="flex gap-2 text-xs">
            <span className="w-24 shrink-0 font-medium">{stage.label}</span>
            <span className="text-muted-foreground">{stage.note}</span>
          </div>
        ))}
      </figcaption>
    </figure>
  );
}
