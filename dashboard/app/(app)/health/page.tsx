import type { Metadata } from "next";

import { FieldList, Panel, type Field } from "@/components/stock/field-list";
import { runFreshness } from "@/components/freshness-banner";
import {
  formatDate,
  formatDateTimeIST,
  formatInteger,
  formatRelativeAge,
  MISSING,
} from "@/lib/format";
import { getLatestRun, getRecentRuns } from "@/lib/queries";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "Run health" };

/** Rating mix columns, in scale order, each with its fill as a header swatch. */
const RATING_COLUMNS = [
  { label: "Str buy", field: "strong_buy_count", swatch: "bg-rating-strong-buy" },
  { label: "Buy", field: "buy_count", swatch: "bg-rating-buy" },
  { label: "Hold", field: "hold_count", swatch: "bg-rating-hold" },
  { label: "Reduce", field: "reduce_count", swatch: "bg-rating-reduce" },
  { label: "Sell", field: "sell_count", swatch: "bg-rating-sell" },
] as const;
export const dynamic = "force-dynamic";

function short(value: string | null | undefined, length = 12): string {
  if (!value) return MISSING;
  return value.length > length ? `${value.slice(0, length)}…` : value;
}

export default async function HealthPage() {
  const [run, recent] = await Promise.all([getLatestRun(), getRecentRuns(20)]);

  if (!run) {
    return (
      <div className="px-4 py-6 sm:px-6">
        <p className="text-sm text-muted-foreground">
          No screener run has been published yet.
        </p>
      </div>
    );
  }

  const freshness = runFreshness(run);

  const collected = run.technical_collected_count ?? 0;
  const requested = run.technical_requested_count ?? 0;
  const collectionRate = requested ? (collected / requested) * 100 : null;

  const provenance: Field[] = [
    { label: "Run date", value: formatDate(run.run_date) },
    { label: "Price bar as of", value: formatDate(run.price_bar_as_of) },
    {
      label: "Published",
      value: formatDateTimeIST(run.generated_at_utc),
      hint: formatRelativeAge(run.generated_at_utc),
    },
    { label: "Ingested", value: formatRelativeAge(run.ingested_at) },
    { label: "Model version", value: run.model_version ?? MISSING },
    {
      label: "Policy version",
      value: run.recommendation_policy_version ?? MISSING,
      hint: "Bumped for a ranking change, separately from the output schema.",
    },
    {
      label: "Output schema",
      value: run.output_schema_version ?? MISSING,
      hint: "Bumped for additive audit columns that do not change the signal.",
    },
    {
      label: "Git SHA",
      value: short(run.git_sha, 10),
      tone: run.git_dirty ? "caution" : "default",
      hint: run.git_dirty
        ? "Working tree was dirty: this run is not reproducible from a commit alone."
        : undefined,
    },
    { label: "Config hash", value: short(run.config_sha256, 10) },
    { label: "Market calendar", value: run.market_calendar_version ?? MISSING },
  ];

  const collection: Field[] = [
    { label: "Rows published", value: formatInteger(run.row_count) },
    {
      label: "Universe selected",
      value: formatInteger(run.universe_selected_count ?? 0),
    },
    {
      label: "Technical requested",
      value: formatInteger(requested),
    },
    {
      label: "Technical collected",
      value: collectionRate
        ? `${formatInteger(collected)} (${collectionRate.toFixed(1)}%)`
        : formatInteger(collected),
      tone:
        collectionRate !== null && collectionRate < 90 ? "caution" : "positive",
    },
    {
      label: "Provider failures",
      value: formatInteger(run.technical_failed_count ?? 0),
      tone: (run.technical_failed_count ?? 0) > 0 ? "caution" : "muted",
      hint:
        (run.technical_failed_count ?? 0) > 0
          ? "A prior completed row may have been retained as stale evidence; its policy tab shows the session-alignment gate."
          : undefined,
    },
    {
      label: "Fundamentals missing",
      value: formatInteger(run.fundamental_missing_count ?? 0),
      tone: (run.fundamental_missing_count ?? 0) > 0 ? "caution" : "muted",
      hint: "A missing fundamental reduces coverage, which is a gate rather than a neutral gap.",
    },
  ];

  return (
    <div className="space-y-4 px-4 py-5 sm:px-6">
        <div className="animate-rise">
          <h1 className="text-title font-semibold">Run health</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Provenance and collection diagnostics for the run currently being
            served.
          </p>
        </div>

        <div
          className={cn(
            "rounded-panel border p-5 elevate-panel",
            freshness.level === "ok"
              ? "border-positive/30 bg-positive/5"
              : freshness.level === "warn"
                ? "border-caution/30 bg-caution/5"
                : "border-destructive/30 bg-destructive/5",
          )}
        >
          <p className="text-sm font-medium">
            {freshness.level === "ok"
              ? "Pipeline is current"
              : "Pipeline attention needed"}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {freshness.level === "ok"
              ? `Serving the run for ${formatDate(run.price_bar_as_of ?? run.run_date)}, published ${formatRelativeAge(run.generated_at_utc)}.`
              : freshness.message}
          </p>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <Panel
            title="Provenance"
            description="Enough to reproduce this run exactly, or to prove two runs differ."
          >
            <FieldList fields={provenance} columns={2} />
          </Panel>

          <Panel
            title="Collection"
            description="What the collector asked for versus what it got."
          >
            <FieldList fields={collection} columns={2} />
          </Panel>
        </div>

        <Panel
          title="Recent runs"
          description="Rating mix per published run. A sharp shift in the mix without a model-version change is worth investigating."
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                {/*
                  The rating hue lives in a header swatch, not in the figures.
                  These are fill colours -- #4ade80 BUY measures 1.66:1 as text
                  on the card -- so colouring five columns of counts with them
                  made the numbers barely readable. One swatch per column
                  carries the same mapping and leaves the figures legible.
                */}
                <tr className="border-b text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  <th scope="col" className="py-2 pr-3 text-left">Run</th>
                  <th scope="col" className="py-2 pr-3 text-right">Rows</th>
                  {RATING_COLUMNS.map((column) => (
                    <th
                      key={column.label}
                      scope="col"
                      className="py-2 pr-3 text-right whitespace-nowrap"
                    >
                      <span className="inline-flex items-center gap-1.5">
                        <span
                          className={cn(
                            "size-2 shrink-0 rounded-full ring-1 ring-inset ring-black/15",
                            column.swatch,
                          )}
                          aria-hidden
                        />
                        {column.label}
                      </span>
                    </th>
                  ))}
                  <th scope="col" className="py-2 text-left">Model</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((item) => (
                  <tr
                    key={item.run_date}
                    className="border-b transition-colors duration-(--duration-fast) last:border-0 hover:bg-muted/40"
                  >
                    <td className="tabular py-1.5 pr-3 font-mono text-xs">
                      {formatDate(item.run_date)}
                    </td>
                    <td className="tabular py-1.5 pr-3 text-right font-mono text-xs">
                      {formatInteger(item.row_count)}
                    </td>
                    {RATING_COLUMNS.map((column) => (
                      <td
                        key={column.label}
                        className="tabular py-1.5 pr-3 text-right font-mono text-xs"
                      >
                        {formatInteger(item[column.field] as number)}
                      </td>
                    ))}
                    <td className="py-1.5 font-mono text-[11px] text-muted-foreground">
                      {short(item.model_version, 18)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

      <p className="text-xs leading-relaxed text-muted-foreground">
        {run.model_validation_status ??
          "Research model; point-in-time out-of-sample validation pending."}
      </p>
    </div>
  );
}
