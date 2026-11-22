import { ChevronRight } from "lucide-react";
import Link from "next/link";

import { FLOW_INK, FLOW_LABEL, flowFormat, type FlowCategory } from "@/components/market/flow-format";
import { fortnightLabel, fortnightMonth } from "@/lib/fpi-flows.mjs";
import { formatDate } from "@/lib/format";
import type { Market } from "@/lib/markets";
import { cn } from "@/lib/utils";

type Side = number | null;
type Summary = {
  date: string;
  bars: { fii: Side; dii: Side }[];
  fiveDay: { sessions: number; fii: Side; dii: Side };
  monthToDate: { sessions: number; fii: Side; dii: Side };
};
type Extreme = { sector: string; net: number } | null;
type Extremes = { start: string; end: string; bought: Extreme; sold: Extreme } | null;

/**
 * The Breadth page's flows in brief: today's FII/FPI and DII net with their
 * five-session and month-to-date sums (lib/market-flows.mjs, flowSummary), and
 * the latest NSDL fortnight's most bought and most sold sector
 * (lib/fpi-flows.mjs, sectorExtremes). The chart and the full tables are the
 * Flows page's, which the heading opens.
 */
export function FlowsSummary({
  market,
  summary,
  sectors,
  href,
}: {
  market: Market;
  summary: Summary | null;
  sectors: Extremes;
  href: string;
}) {
  if (!summary && !sectors) return null;
  const { signed, tone } = flowFormat(market);
  const today = summary?.bars.at(-1);
  const month = summary ? fortnightMonth(summary.date) : "";

  const side = (key: FlowCategory, field: "fii" | "dii") => (
    <div className="min-w-0 p-4 sm:p-5">
      <p className="inline-flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <span className="size-2 rounded-[2px]" style={{ background: FLOW_INK[key] }} aria-hidden />
        {FLOW_LABEL[key]}
      </p>
      <p className={cn("tabular mt-1.5 font-mono text-lg font-semibold", tone(today?.[field]))}>
        {signed(today?.[field])}
      </p>
      <dl className="tabular mt-2 space-y-0.5 text-xs">
        <div className="flex justify-between gap-3">
          <dt className="text-muted-foreground" title="Last 5 sessions">5D</dt>
          <dd className={cn("font-mono whitespace-nowrap", tone(summary?.fiveDay[field]))}>{signed(summary?.fiveDay[field])}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-muted-foreground" title={`${month} to date`}>MTD</dt>
          <dd className={cn("font-mono whitespace-nowrap", tone(summary?.monthToDate[field]))}>{signed(summary?.monthToDate[field])}</dd>
        </div>
      </dl>
    </div>
  );

  const extreme = (label: string, entry: Extreme) => (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="min-w-0 truncate">
        <span className="text-muted-foreground">{label} · </span>
        <span className="font-medium">{entry?.sector ?? "None"}</span>
      </dt>
      <dd className={cn("tabular shrink-0 font-mono text-xs", tone(entry?.net))}>{signed(entry?.net)}</dd>
    </div>
  );

  return (
    <section aria-labelledby="flows-summary-title" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="flows-summary-title" className="text-lead font-semibold tracking-[-0.011em]">
          <Link
            href={href}
            className="group inline-flex items-center gap-1 rounded hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Investor flows
            <ChevronRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden />
          </Link>
        </h2>
        {summary ? (
          <p className="tabular text-xs text-muted-foreground">NSE provisional · {formatDate(summary.date)}</p>
        ) : null}
      </div>

      <div className="panel grid grid-cols-2 lg:grid-cols-[1fr_1fr_1.5fr]">
        {summary ? (
          <>
            {side("FII", "fii")}
            <div className="border-l border-border/60">{side("DII", "dii")}</div>
          </>
        ) : null}
        {sectors ? (
          <div
            className={cn(
              "col-span-2 min-w-0 p-4 sm:p-5 lg:col-span-1",
              summary && "border-t border-border/60 lg:border-t-0 lg:border-l",
            )}
          >
            <p className="text-xs font-medium text-muted-foreground">
              FPI by sector · {fortnightLabel(sectors.start, sectors.end)}
            </p>
            <dl className="mt-2.5 space-y-2 text-sm">
              {extreme("Bought", sectors.bought)}
              {extreme("Sold", sectors.sold)}
            </dl>
          </div>
        ) : null}
      </div>
    </section>
  );
}
