import type { Metadata } from "next";

import { AppShell } from "@/components/app-shell";
import { FieldList, Panel, type Field } from "@/components/stock/field-list";
import { runFreshness } from "@/components/freshness-banner";
import { requireAccess } from "@/lib/auth";
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
export const dynamic = "force-dynamic";

function short(value: string | null | undefined, length = 12): string {
  if (!value) return MISSING;
  return value.length > length ? `${value.slice(0, length)}…` : value;
}

export default async function HealthPage() {
  const viewer = await requireAccess();
  const [run, recent] = await Promise.all([getLatestRun(), getRecentRuns(20)]);

  if (!run) {
    return (
      <AppShell run={null} viewer={viewer}>
        <div className="px-4 py-6 sm:px-6">
          <p className="text-sm text-muted-foreground">
            No screener run has been published yet.
          </p>
        </div>
      </AppShell>
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
      label: "Technical failed",
      value: formatInteger(run.technical_failed_count ?? 0),
      tone: (run.technical_failed_count ?? 0) > 0 ? "caution" : "muted",
    },
    {
      label: "Fundamentals missing",
      value: formatInteger(run.fundamental_missing_count ?? 0),
      tone: (run.fundamental_missing_count ?? 0) > 0 ? "caution" : "muted",
      hint: "A missing fundamental reduces coverage, which is a gate rather than a neutral gap.",
    },
  ];

  return (
    <AppShell run={run} viewer={viewer}>
      <div className="space-y-4 px-4 py-5 sm:px-6">
        <div>
          <h1 className="text-lg font-semibold">Run health</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Provenance and collection diagnostics for the run currently being
            served.
          </p>
        </div>

        <div
          className={cn(
            "rounded-lg border p-4",
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
                <tr className="border-b text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th scope="col" className="py-2 pr-3 text-left">Run</th>
                  <th scope="col" className="py-2 pr-3 text-right">Rows</th>
                  <th scope="col" className="py-2 pr-3 text-right">Str buy</th>
                  <th scope="col" className="py-2 pr-3 text-right">Buy</th>
                  <th scope="col" className="py-2 pr-3 text-right">Hold</th>
                  <th scope="col" className="py-2 pr-3 text-right">Reduce</th>
                  <th scope="col" className="py-2 pr-3 text-right">Sell</th>
                  <th scope="col" className="py-2 text-left">Model</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((item) => (
                  <tr key={item.run_date} className="border-b last:border-0">
                    <td className="tabular py-1.5 pr-3 font-mono text-xs">
                      {formatDate(item.run_date)}
                    </td>
                    <td className="tabular py-1.5 pr-3 text-right font-mono text-xs">
                      {formatInteger(item.row_count)}
                    </td>
                    <td className="tabular py-1.5 pr-3 text-right font-mono text-xs text-rating-strong-buy">
                      {item.strong_buy_count}
                    </td>
                    <td className="tabular py-1.5 pr-3 text-right font-mono text-xs text-rating-buy">
                      {item.buy_count}
                    </td>
                    <td className="tabular py-1.5 pr-3 text-right font-mono text-xs text-muted-foreground">
                      {item.hold_count}
                    </td>
                    <td className="tabular py-1.5 pr-3 text-right font-mono text-xs text-rating-reduce">
                      {item.reduce_count}
                    </td>
                    <td className="tabular py-1.5 pr-3 text-right font-mono text-xs text-rating-sell">
                      {item.sell_count}
                    </td>
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
    </AppShell>
  );
}
