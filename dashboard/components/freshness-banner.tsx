import { AlertTriangle, Info } from "lucide-react";

import { cn } from "@/lib/utils";
import { daysSince, formatDate, formatRelativeAge } from "@/lib/format";
import type { ScreenerRun } from "@/lib/types";

/**
 * Freshness state.
 *
 * The screener runs once per trading day after the 16:15 IST bar-completion
 * cutoff, so data being a day old is normal on a weekend or exchange holiday
 * and is not worth alarming about. What matters is a gap large enough to mean
 * the pipeline stopped: the thresholds below are deliberately generous so the
 * warning keeps its meaning rather than becoming background noise.
 */
export function runFreshness(run: ScreenerRun | null) {
  if (!run) {
    return {
      level: "critical" as const,
      message: "No screener run has been published yet.",
    };
  }

  const age = daysSince(run.price_bar_as_of ?? run.run_date);

  if (age === null) {
    return { level: "info" as const, message: "Run date unavailable." };
  }
  if (age >= 5) {
    return {
      level: "critical" as const,
      message: `Data is ${age} days old. The daily pipeline has probably stopped.`,
    };
  }
  if (age >= 3) {
    return {
      level: "warn" as const,
      message: `Data is ${age} days old, which is longer than a normal weekend gap.`,
    };
  }
  return { level: "ok" as const, message: "" };
}

export function FreshnessBanner({ run }: { run: ScreenerRun | null }) {
  const freshness = runFreshness(run);
  if (freshness.level === "ok") return null;

  const critical = freshness.level === "critical";

  return (
    <div
      role="status"
      className={cn(
        "flex items-start gap-2.5 border-b px-4 py-2.5 text-sm sm:px-6",
        critical
          ? "border-destructive/30 bg-destructive/8 text-destructive"
          : "border-caution/30 bg-caution/8 text-caution",
      )}
    >
      {critical ? (
        <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      ) : (
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
      )}
      <p>
        <span className="font-medium">{freshness.message}</span>{" "}
        {run ? (
          <span className="opacity-90">
            Showing the run for {formatDate(run.price_bar_as_of ?? run.run_date)}
            , published {formatRelativeAge(run.generated_at_utc)}.
          </span>
        ) : null}
      </p>
    </div>
  );
}
