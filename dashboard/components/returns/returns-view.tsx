"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, useTransition } from "react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";

import { RatingBadge } from "@/components/rating-badge";
import { ReturnsChart } from "@/components/returns/returns-chart";
import { SegmentedControl } from "@/components/segmented-control";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { formatDate, formatMoney, formatPercent, MISSING } from "@/lib/format";
import { rangeStart } from "@/lib/market-breadth.mjs";
import { marketPath, type Market } from "@/lib/markets";
import {
  COST_PER_SIDE_PCT,
  REBALANCE_OPTIONS,
  START_PRESETS,
  TOP_N_OPTIONS,
  modelForDate,
  snapRankingDate,
} from "@/lib/returns.mjs";
import type { HoldingRow, ReturnsReport } from "@/lib/returns-data";
import { STAGES } from "@/lib/types";
import { cn } from "@/lib/utils";

type Report = Extract<ReturnsReport, { status: "ok" }>;

const CUSTOM = "custom";

const STAGE_TONE: Record<string, string> = {
  positive: "text-positive",
  negative: "text-negative",
  caution: "text-caution",
  neutral: "text-foreground",
  muted: "text-muted-foreground",
};

/**
 * The Returns page body: controls, the headline figures, the chart, and the
 * holdings behind them.
 *
 * Every control is in the URL, so a result can be linked and Back undoes a
 * change. The server does the pricing; while it works the body dims rather
 * than blanking, as the Market page does for a group change.
 */
export function ReturnsView({ report, market }: { report: Report; market: Market }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();

  const push = (mutate: (params: URLSearchParams) => void) => {
    const next = new URLSearchParams(searchParams.toString());
    mutate(next);
    const query = next.toString();
    startTransition(() => router.push(query ? `${pathname}?${query}` : pathname, { scroll: false }));
  };

  const first = report.rankingDates[0];
  const last = report.rankingDates[report.rankingDates.length - 1];

  // A shortcut is offered only when the history reaches back that far; before
  // then it would resolve to the first ranking and duplicate "All".
  const presets = START_PRESETS.flatMap((preset) => {
    const start =
      preset.months === null && !preset.days
        ? first
        : rangeStart(report.asOf, preset.months ?? null, preset.days ?? null);
    if (!start || start < first) return [];
    return [{ label: preset.label, date: snapRankingDate(report.rankingDates, start)! }];
  });
  const activePreset = presets.find((preset) => preset.date === report.rankDate)?.label ?? CUSTOM;
  const presetOptions = [
    ...presets.map((preset) => ({ value: preset.label, label: preset.label })),
    ...(activePreset === CUSTOM ? [{ value: CUSTOM, label: "Custom" }] : []),
  ];

  const headline = report.costs ? report.basket.netPct : report.basket.grossPct;
  const excess =
    headline !== null && report.benchmark.returnPct !== null ? headline - report.benchmark.returnPct : null;
  const sessionsHeld = report.basket.curve.length;
  const rebalanceLabel = REBALANCE_PERIOD_WORDS[report.rebalance.option] ?? null;
  const lastModel = modelForDate(market.code, report.rebalance.lastRankDate);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
        <Field label="Start">
          <div className="flex flex-wrap items-center gap-2">
            <SegmentedControl
              label="Start date shortcut"
              value={activePreset}
              onChange={(value) => {
                const preset = presets.find((item) => item.label === value);
                if (preset) push((params) => params.set("from", preset.date));
              }}
              options={presetOptions}
            />
            <Input
              type="date"
              aria-label="Ranking date"
              className="h-9 w-40 tabular"
              min={first}
              max={last}
              value={report.rankDate}
              onChange={(event) => {
                const value = event.target.value;
                if (value) push((params) => params.set("from", value));
              }}
            />
          </div>
        </Field>
        <Field label="Basket">
          <SegmentedControl
            label="Basket size"
            value={String(report.topN)}
            onChange={(value) => push((params) => params.set("top", value))}
            options={TOP_N_OPTIONS.map((size) => ({ value: String(size), label: `Top ${size}` }))}
          />
        </Field>
        <Field label="Rebalance">
          <RebalanceSlider
            value={report.rebalance.option}
            onCommit={(value) =>
              push((params) => (value === "never" ? params.delete("rebalance") : params.set("rebalance", value)))
            }
          />
        </Field>
        <Field label="Costs">
          <SegmentedControl
            label="Trading costs"
            value={report.costs ? "net" : "gross"}
            onChange={(value) =>
              push((params) => (value === "gross" ? params.set("costs", "gross") : params.delete("costs")))
            }
            options={[
              { value: "net", label: `${COST_PER_SIDE_PCT}% a side`, title: "Charged on the buy and on the sale" },
              { value: "gross", label: "None" },
            ]}
          />
        </Field>
      </div>

      <div
        aria-busy={pending}
        className={cn(
          "space-y-4 transition-opacity duration-(--duration-fast) ease-(--ease-standard)",
          pending && "opacity-60",
        )}
      >
        <p className="text-sm text-muted-foreground">
          The top {report.topN} of the{" "}
          <span className="font-medium text-foreground">{formatDate(report.rankDate)}</span> ranking
          {report.model ? ` (${report.model})` : ""}, bought at the close on {formatDate(report.entrySession)}
          {rebalanceLabel ? (
            report.rebalance.count ? (
              <>
                , rebuilt every {rebalanceLabel} from the latest ranking &mdash; {report.rebalance.count}{" "}
                {report.rebalance.count === 1 ? "rebalance" : "rebalances"}, {report.rebalance.bought}{" "}
                {report.rebalance.bought === 1 ? "name" : "names"} swapped
                {lastModel && lastModel !== report.model ? `, latest ranking ${lastModel}` : ""} &mdash; and
              </>
            ) : (
              <> (no rebalance falls inside this window) and</>
            )
          ) : (
            " and"
          )}{" "}
          held for {sessionsHeld} {sessionsHeld === 1 ? "session" : "sessions"} to {formatDate(report.asOf)}.
        </p>

        <section className="panel grid grid-cols-2 divide-border lg:grid-cols-4 lg:divide-x">
          <Tile
            label={`Top ${report.topN}`}
            value={headline}
            note={
              report.costs
                ? report.rebalance.count
                  ? `after ${report.rebalance.costPct.toFixed(2)} pts of trading costs`
                  : `after ${COST_PER_SIDE_PCT}% costs each way`
                : "before costs"
            }
            emphasis
          />
          <Tile
            label={report.benchmark.name}
            value={report.benchmark.returnPct}
            note={
              report.benchmark.through && report.benchmark.through !== report.asOf
                ? `through ${formatDate(report.benchmark.through)}`
                : "index level"
            }
          />
          <Tile
            label="All ranked stocks"
            value={report.universe.returnPct}
            note={`equal weight, ${report.universe.counted.toLocaleString(market.locale)} of ${report.universe.total.toLocaleString(market.locale)}`}
          />
          <Tile
            label={`Top ${report.topN} vs ${report.benchmark.name}`}
            value={excess}
            unit="pts"
            note="difference in return"
          />
        </section>

        <ReturnsChart
          basket={report.basket.curve}
          benchmark={report.benchmark.curve}
          basketLabel={`Top ${report.topN}`}
          benchmarkLabel={report.benchmark.name}
        />

        <Holdings
          holdings={report.holdings}
          market={market}
          topN={report.topN}
          rankDate={report.rebalance.lastRankDate}
          rebalanced={report.rebalance.count > 0}
          firstEntry={report.entrySession}
        />
      </div>
    </div>
  );
}

/** How a rebalance period reads inside a sentence. */
const REBALANCE_PERIOD_WORDS: Record<string, string> = {
  "1w": "week",
  "2w": "two weeks",
  "1m": "month",
  "3m": "three months",
};

/**
 * A stepped slider over the fixed rebalance periods.
 *
 * The label follows the thumb while it moves; the page is asked for only when
 * it is let go, so dragging across four stops costs one server round trip,
 * not four.
 */
function firstValue(value: number | readonly number[]) {
  return typeof value === "number" ? value : value[0];
}

function RebalanceSlider({ value, onCommit }: { value: string; onCommit: (value: string) => void }) {
  const committed = Math.max(0, REBALANCE_OPTIONS.findIndex((option) => option.value === value));
  const [dragging, setDragging] = useState<number | null>(null);
  const index = dragging ?? committed;
  return (
    <div className="flex h-9 w-56 items-center gap-3">
      <Slider
        aria-label="Rebalance every"
        min={0}
        max={REBALANCE_OPTIONS.length - 1}
        step={1}
        // An array, not a number: the shared Slider renders one thumb per
        // value and falls back to a two-thumb range when given a bare number.
        value={[index]}
        onValueChange={(next) => setDragging(firstValue(next))}
        onValueCommitted={(next) => {
          setDragging(null);
          const stop = firstValue(next);
          if (stop !== committed) onCommit(REBALANCE_OPTIONS[stop].value);
        }}
        className="flex-1"
      />
      <span className="tabular w-12 text-sm font-semibold">{REBALANCE_OPTIONS[index].label}</span>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      {children}
    </div>
  );
}

function Tile({
  label,
  value,
  note,
  unit = "%",
  emphasis = false,
}: {
  label: string;
  value: number | null;
  note: string;
  unit?: "%" | "pts";
  emphasis?: boolean;
}) {
  const text =
    value === null
      ? MISSING
      : unit === "pts"
        ? `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(2)} pts`
        : formatPercent(value, 2, true);
  return (
    <div className="min-w-0 px-4 py-3 sm:px-5 sm:py-4">
      <p className="truncate text-xs font-medium text-muted-foreground">{label}</p>
      <p
        className={cn(
          "numeral mt-1 leading-tight font-semibold tracking-[-0.02em] tabular",
          emphasis ? "text-[1.75rem]" : "text-[1.375rem]",
          value === null ? "text-muted-foreground" : value >= 0 ? "text-positive" : "text-negative",
        )}
      >
        {text}
      </p>
      <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{note}</p>
    </div>
  );
}

function StageText({ stage }: { stage: string | null }) {
  const meta = STAGES.find((item) => item.value === stage);
  if (!meta) return <span className="text-muted-foreground">{MISSING}</span>;
  return (
    <span title={meta.meaning} className={cn("font-mono text-xs font-semibold", STAGE_TONE[meta.tone])}>
      {meta.short}
    </span>
  );
}

function ReturnText({ value }: { value: number | null }) {
  if (value === null) return <span className="text-muted-foreground">{MISSING}</span>;
  return (
    <span className={cn("tabular font-mono text-xs font-semibold", value >= 0 ? "text-positive" : "text-negative")}>
      {formatPercent(value, 2, true)}
    </span>
  );
}

function RankNow({ row, topN }: { row: HoldingRow; topN: number }) {
  if (!row.inLatestRun || row.rankNow === null) {
    return <span className="whitespace-nowrap text-[11px] text-muted-foreground">not ranked</span>;
  }
  const change = row.rankThen !== null ? row.rankThen - row.rankNow : 0;
  return (
    <span className="inline-flex items-center gap-1">
      <span className={cn("tabular font-mono text-xs", row.rankNow > topN && "text-muted-foreground")}>
        {row.rankNow}
      </span>
      {change ? (
        <span
          className={cn(
            "tabular inline-flex items-center font-mono text-[11px]",
            change > 0 ? "text-positive" : "text-negative",
          )}
        >
          {change > 0 ? <ArrowUpRight className="size-3" aria-hidden /> : <ArrowDownRight className="size-3" aria-hidden />}
          {Math.abs(change)}
        </span>
      ) : null}
    </span>
  );
}

function Holdings({
  holdings,
  market,
  topN,
  rankDate,
  rebalanced,
  firstEntry,
}: {
  holdings: HoldingRow[];
  market: Market;
  topN: number;
  /** The ranking the current holdings were last bought from. */
  rankDate: string;
  rebalanced: boolean;
  firstEntry: string;
}) {
  const priced = holdings.filter((row) => row.returnPct !== null);
  const winners = priced.filter((row) => row.returnPct! > 0).length;

  return (
    <section className="panel overflow-hidden">
      <div className="border-b px-4 py-3">
        <h2 className="text-base font-semibold tracking-[-0.011em]">Holdings</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {winners} of {priced.length} up.{" "}
          {rebalanced ? (
            <>
              The basket after its last rebalance, on the {formatDate(rankDate)} ranking. Each return runs from
              when that stock was bought; rank, stage and rating are shown as of that ranking and today.
            </>
          ) : (
            <>
              Rank, stage and rating as of {formatDate(rankDate)} and today; a name that has left the top {topN}{" "}
              is still held, because the basket is bought once and not rebalanced.
            </>
          )}
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm sm:min-w-[640px]">
          <thead>
            <tr className="border-b text-left text-[11px] font-medium text-muted-foreground">
              <th className="px-4 py-2 font-medium">#</th>
              <th className="px-2 py-2 font-medium">Stock</th>
              <th className="hidden px-2 py-2 text-right font-medium sm:table-cell">Entry</th>
              <th className="hidden px-2 py-2 text-right font-medium sm:table-cell">Latest</th>
              <th className="px-2 py-2 text-right font-medium">Return</th>
              <th className="px-2 py-2 font-medium">Rank now</th>
              <th className="hidden px-2 py-2 font-medium sm:table-cell">Stage</th>
              <th className="px-4 py-2 font-medium">Rating now</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {holdings.map((row) => (
              <tr key={row.symbol} className="hover:bg-muted/50">
                <td className="tabular px-4 py-2 font-mono text-xs text-muted-foreground">{row.rankThen ?? MISSING}</td>
                <td className="max-w-[16rem] px-2 py-2">
                  <Link
                    href={marketPath(market.slug, `/stocks/${encodeURIComponent(row.symbol)}`)}
                    className="block font-mono text-xs font-semibold underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {row.symbol}
                  </Link>
                  <span className="block truncate text-[11px] text-muted-foreground">{row.company ?? MISSING}</span>
                </td>
                <td className="tabular hidden px-2 py-2 text-right font-mono text-xs sm:table-cell">
                  {row.entry ? formatMoney(row.entry.close, market, market.listPriceDigits) : MISSING}
                  {row.delayedEntry && row.entry ? (
                    <span className="block whitespace-nowrap text-[10px] text-caution" title="Did not trade on the entry session">
                      bought {formatDate(row.entry.time)}
                    </span>
                  ) : row.entry && row.heldSince && row.heldSince !== firstEntry ? (
                    <span className="block whitespace-nowrap text-[10px] text-muted-foreground">
                      since {formatDate(row.heldSince)}
                    </span>
                  ) : null}
                </td>
                <td className="tabular hidden px-2 py-2 text-right font-mono text-xs sm:table-cell">
                  {row.last ? formatMoney(row.last.close, market, market.listPriceDigits) : MISSING}
                </td>
                <td className="px-2 py-2 text-right">
                  <ReturnText value={row.returnPct} />
                </td>
                <td className="px-2 py-2">
                  <RankNow row={row} topN={topN} />
                </td>
                <td className="hidden px-2 py-2 sm:table-cell">
                  <span className="inline-flex items-center gap-1 text-muted-foreground">
                    <StageText stage={row.stageThen} />
                    <span aria-label="now">→</span>
                    <StageText stage={row.stageNow} />
                  </span>
                </td>
                <td className="px-4 py-2">
                  {row.ratingNow ? <RatingBadge rating={row.ratingNow} /> : <span className="text-muted-foreground">{MISSING}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
