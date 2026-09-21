import { TriangleAlert } from "lucide-react";

import { FieldList, type Field } from "@/components/stock/field-list";
import type { ChartMarker } from "@/components/stock/price-chart";
import { formatDate, formatMoney, formatPercent, MISSING } from "@/lib/format";
import type { Market } from "@/lib/markets";
import { STAGES, type SnapshotRow } from "@/lib/types";

type StageRow = Pick<
  SnapshotRow,
  | "stage"
  | "days_in_stage"
  | "stage_entry_date"
  | "return_since_stage_entry_pct"
  | "stage2_entry_date"
  | "stage2_entry_price"
  | "stage2_exit_date"
  | "stage2_entry_censored"
  | "return_since_stage2_entry_pct"
  | "advance_age_days"
  | "advance_age_censored"
  | "rs_rating"
  | "rs_rating_change_1m"
  | "price_to_ma150_pct"
  | "pct_from_52w_high"
  | "breakdown_date"
  | "breakdown_from"
>;

const TONE_CLASS: Record<string, string> = {
  positive: "text-positive",
  negative: "text-negative",
  caution: "text-caution",
  neutral: "text-foreground",
  muted: "text-muted-foreground",
};

function signedTone(value: number | null | undefined): Field["tone"] {
  if (value === null || value === undefined) return "muted";
  return value >= 0 ? "positive" : "negative";
}

function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);
}

/** Markers for the price chart: where the latest advance entered Stage 2, and
 *  where the current Stage 3/4 run began. */
export function stageMarkers(row: StageRow): ChartMarker[] {
  const markers: ChartMarker[] = [];
  if (row.stage2_entry_date && !row.stage2_entry_censored) {
    markers.push({ time: row.stage2_entry_date, label: "Stage 2", tone: "positive" });
  }
  if (row.breakdown_date) {
    const stage = STAGES.find((item) => item.value === row.stage);
    markers.push({ time: row.breakdown_date, label: stage?.short ?? "S3/S4", tone: "caution" });
  }
  return markers;
}

/**
 * Where the stock is in its cycle, and what it has done since it got there.
 *
 * Display evidence only. Stage never enters the score or rank -- blending it
 * in lowered returns in every validation window (P3, P4) -- but two parts of
 * it are worth reading: the date the latest advance entered Stage 2, with the
 * return since, and a break into Stage 3/4, which is the one stage rule that
 * tested as a useful exit (P5).
 */
export function StageSummary({
  row,
  asOf,
  market,
}: {
  row: StageRow;
  /** The run's bar date, to state "N days ago" against the data, not today. */
  asOf: string | null;
  /** Whose currency the Stage 2 entry price is in. */
  market: Market;
}) {
  const stage = STAGES.find((item) => item.value === row.stage);
  if (!stage) {
    return (
      <p className="text-sm text-muted-foreground">
        No stage for this stock in the current run: its price history is shorter
        than the 221 sessions the 200-day average and its slope need.
      </p>
    );
  }

  const inAdvance = row.stage === "Stage 2" || row.stage === "S2 Candidate";
  const stage2Label = row.stage2_entry_date
    ? `${row.stage2_entry_censored ? "on or before " : ""}${formatDate(row.stage2_entry_date)}`
    : null;
  const stage2Ago =
    row.stage2_entry_date && asOf ? daysBetween(row.stage2_entry_date, asOf) : null;

  const fields: Field[] = [
    {
      label: "In this stage since",
      value: row.stage_entry_date ? formatDate(row.stage_entry_date) : MISSING,
      hint:
        row.days_in_stage !== null
          ? `${row.days_in_stage} days · ${formatPercent(row.return_since_stage_entry_pct, 1, true)} since`
          : undefined,
    },
    {
      label: "Entered Stage 2",
      value: stage2Label ?? "No Stage 2 in the data",
      tone: stage2Label ? "default" : "muted",
      hint: row.stage2_entry_date
        ? `${stage2Ago !== null ? `${stage2Ago} days ago · ` : ""}at ${formatMoney(row.stage2_entry_price, market)}${
            row.stage2_entry_censored
              ? " · the advance was under way when the price history begins"
              : ""
          }`
        : undefined,
    },
    {
      label: "Return since Stage 2 entry",
      value: formatPercent(row.return_since_stage2_entry_pct, 1, true),
      tone: signedTone(row.return_since_stage2_entry_pct),
      hint: row.stage2_exit_date
        ? `The advance ended on ${formatDate(row.stage2_exit_date)}; return measured to today`
        : inAdvance
          ? `Advance still running${
              row.advance_age_days !== null
                ? ` · ${row.advance_age_censored ? "at least " : ""}${row.advance_age_days} days`
                : ""
            }`
          : undefined,
    },
    {
      label: "RS rating",
      value:
        row.rs_rating !== null && row.rs_rating !== undefined
          ? `${Math.round(row.rs_rating)}${
              row.rs_rating_change_1m !== null && row.rs_rating_change_1m !== undefined
                ? ` (${row.rs_rating_change_1m >= 0 ? "+" : ""}${Math.round(row.rs_rating_change_1m)} in 1M)`
                : ""
            }`
          : MISSING,
      hint: "1-99, 3/6/9/12-month returns weighted 40/20/20/20",
    },
    {
      label: "vs 150-day average",
      value: formatPercent(row.price_to_ma150_pct, 1, true),
      tone: signedTone(row.price_to_ma150_pct),
    },
    {
      label: "From 52-week high",
      value: formatPercent(row.pct_from_52w_high, 1, true),
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className={`font-mono text-lg font-semibold ${TONE_CLASS[stage.tone]}`}>
          {stage.value}
        </span>
        <span className="text-sm text-muted-foreground">{stage.meaning}</span>
      </div>

      {row.breakdown_date ? (
        <div className="flex items-start gap-2 rounded-row border border-caution/40 px-3 py-2">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-caution" aria-hidden />
          <p className="text-sm">
            Broke into {row.stage} on {formatDate(row.breakdown_date)}
            {row.breakdown_from ? ` from ${row.breakdown_from}` : ""}.{" "}
            <span className="text-muted-foreground">
              This is the tested exit signal: in 2018-2026, selling a top-20 holding
              the session after such a break cut the worst drawdown from −43% to
              −30%, at a cost of a few points in steady bull years.
            </span>
          </p>
        </div>
      ) : null}

      <FieldList fields={fields} columns={3} />

      <p className="text-[11px] leading-snug text-muted-foreground">
        Stage is shown, not scored: adding it to the ranking lowered returns in
        every validation window, so the rank and rating above ignore it. Returns
        are on the same adjusted closes the model scores.
      </p>
    </div>
  );
}
