"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useOptimistic, useState, useTransition } from "react";

import { ReturnsChart } from "@/components/returns/returns-chart";
import { Portfolio } from "@/components/returns/portfolio";
import { SegmentedControl } from "@/components/segmented-control";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { formatDate, formatPercent, MISSING } from "@/lib/format";
import { rangeStart } from "@/lib/market-breadth.mjs";
import type { Market } from "@/lib/markets";
import {
  COST_PER_SIDE_PCT,
  PICK_OPTIONS,
  REBALANCE_OPTIONS,
  START_PRESETS,
  TOP_N_OPTIONS,
  modelForDate,
  pickOption,
  snapRankingDate,
} from "@/lib/returns.mjs";
import type { ReturnSplit, ReturnsReport } from "@/lib/returns-data";
import { cn } from "@/lib/utils";

type Report = Extract<ReturnsReport, { status: "ok" }>;

const CUSTOM = "custom";


/**
 * The Returns page body: controls, the headline figures, the chart, and the
 * holdings behind them.
 *
 * Every control is in the URL, so a result can be linked and Back undoes a
 * change. The server does the pricing; while it works the body dims rather
 * than blanking, as the Market page does for a group change.
 *
 * Three things keep that wait from being felt:
 *
 * - Every control moves on the press (`useOptimistic`), not when the server
 *   answers, so a click is acknowledged in the same frame.
 * - Costs never ask the server: both curves arrive with every report, and the
 *   toggle swaps between them and rewrites the URL in place.
 * - The dim waits 150ms before it starts, so a quick answer does not flash.
 */
export function ReturnsView({ report, market }: { report: Report; market: Market }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();
  const [costs, setCosts] = useState(report.costs);
  const [shown, setShown] = useOptimistic(
    { from: report.rankDate, top: String(report.topN), rebalance: report.rebalance.option, pick: report.pick },
    (current, patch: Partial<{ from: string; top: string; rebalance: string; pick: string }>) => ({ ...current, ...patch }),
  );

  const urlFor = (mutate: (params: URLSearchParams) => void) => {
    const next = new URLSearchParams(searchParams.toString());
    mutate(next);
    const query = next.toString();
    return query ? `${pathname}?${query}` : pathname;
  };
  const push = (
    patch: Partial<{ from: string; top: string; rebalance: string; pick: string }>,
    mutate: (params: URLSearchParams) => void,
  ) => {
    const url = urlFor(mutate);
    startTransition(() => {
      setShown(patch);
      router.push(url, { scroll: false });
    });
  };
  const toggleCosts = (next: boolean) => {
    setCosts(next);
    // Next keeps useSearchParams in step with a native replaceState, so the
    // next navigation carries the choice without this one costing a request.
    window.history.replaceState(
      null,
      "",
      urlFor((params) => (next ? params.delete("costs") : params.set("costs", "gross"))),
    );
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
  const activePreset = presets.find((preset) => preset.date === shown.from)?.label ?? CUSTOM;
  const presetOptions = [
    ...presets.map((preset) => ({ value: preset.label, label: preset.label })),
    ...(activePreset === CUSTOM ? [{ value: CUSTOM, label: "Custom" }] : []),
  ];

  const headline = costs ? report.basket.netPct : report.basket.grossPct;
  const split = costs ? report.basket.split : report.basket.grossSplit;
  const excess =
    headline !== null && report.benchmark.returnPct !== null ? headline - report.benchmark.returnPct : null;
  const sessionsHeld = report.basket.curve.length;
  const rebalanceLabel = REBALANCE_PERIOD_WORDS[report.rebalance.option] ?? null;
  const lastModel = modelForDate(market.code, report.rebalance.lastRankDate);
  const pickPhrase = pickOption(report.pick).phrase ?? null;
  const rounds = report.rebalance.count + 1;

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
                if (preset) push({ from: preset.date }, (params) => params.set("from", preset.date));
              }}
              options={presetOptions}
            />
            <Input
              type="date"
              aria-label="Ranking date"
              className="h-9 w-40 tabular"
              min={first}
              max={last}
              value={shown.from}
              onChange={(event) => {
                const value = event.target.value;
                if (value) push({ from: value }, (params) => params.set("from", value));
              }}
            />
          </div>
        </Field>
        <Field label="Basket">
          <SegmentedControl
            label="Basket size"
            value={shown.top}
            onChange={(value) => push({ top: value }, (params) => params.set("top", value))}
            options={TOP_N_OPTIONS.map((size) => ({ value: String(size), label: `Top ${size}` }))}
          />
        </Field>
        <Field label="Pick from">
          <SegmentedControl
            label="Pick from"
            value={shown.pick}
            onChange={(value) =>
              push({ pick: value }, (params) => (value === "all" ? params.delete("pick") : params.set("pick", value)))
            }
            options={PICK_OPTIONS.map((option) => ({
              value: option.value,
              label: option.label,
              title: option.title,
            }))}
          />
        </Field>
        <Field label="Rebalance">
          <RebalanceSlider
            value={shown.rebalance}
            onCommit={(value) =>
              push({ rebalance: value }, (params) =>
                value === "never" ? params.delete("rebalance") : params.set("rebalance", value),
              )
            }
          />
        </Field>
        <Field label="Costs">
          <SegmentedControl
            label="Trading costs"
            value={costs ? "net" : "gross"}
            onChange={(value) => toggleCosts(value === "net")}
            options={[
              { value: "net", label: `${COST_PER_SIDE_PCT}% a side`, title: "Charged on the buy and on the sale" },
              { value: "gross", label: "None" },
            ]}
          />
        </Field>
        <span
          role="status"
          className={cn(
            "flex h-9 items-center text-xs text-muted-foreground transition-opacity duration-(--duration-fast)",
            pending ? "opacity-100 delay-150" : "opacity-0",
          )}
        >
          {pending ? "Updating…" : ""}
        </span>
      </div>

      <div
        aria-busy={pending}
        className={cn(
          "space-y-4 transition-opacity duration-(--duration-fast) ease-(--ease-standard)",
          pending && "opacity-60 delay-150",
        )}
      >
        <p className="text-sm text-muted-foreground">
          The top {report.topN}
          {pickPhrase ? ` ${pickPhrase} stocks` : ""} of the{" "}
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

        {report.hold ? (
          <p className="text-xs leading-relaxed text-muted-foreground">
            {report.hold === "advancing"
              ? "A stock is bought from this list, then held while it stays in Stage 2 or a pullback within it, and sold at the next rebalance after it breaks into Stage 3 or 4 — so it is not sold merely for no longer being on the list. "
              : "A stock is bought from this list, then held while it stays rated BUY or better, and sold at the next rebalance after its rating falls below that. "}
            Each rebalance refills the free slots from the list, best first.
          </p>
        ) : null}

        {report.pickStartMovedFrom || report.shortRounds ? (
          <p className="text-xs leading-relaxed text-muted-foreground">
            {report.pickStartMovedFrom ? (
              <>
                The start moved from {formatDate(report.pickStartMovedFrom)} to {formatDate(report.rankDate)}: ratings
                exist in the backtest only once its filings carry enough fundamentals to rate, from 2023.{" "}
              </>
            ) : null}
            {report.shortRounds ? (
              <>
                On {report.shortRounds === rounds ? "every" : `${report.shortRounds} of ${rounds}`}{" "}
                {rounds === 1 ? "purchase" : "rounds"}, fewer than {report.topN} stocks passed the pick; the basket
                held the ones that did in equal weight, and cash when none did.
              </>
            ) : null}
          </p>
        ) : null}

        {report.backtestRounds ? (
          <p className="rounded-xl border border-caution/40 bg-caution/10 px-3 py-2 text-xs leading-relaxed text-foreground">
            <span className="font-semibold">Backtest.</span>{" "}
            {report.backtestRounds === report.rebalance.count + 1
              ? "Every ranking used here is"
              : `${report.backtestRounds} of the ${report.rebalance.count + 1} rankings used here are`}{" "}
            a point-in-time backtest, not one the dashboard published; published rankings begin{" "}
            {formatDate(report.liveFrom)}. The model&rsquo;s weights were fitted on this same period, so
            these returns are in-sample and flatter what to expect going forward.
            {pickOption(report.pick).ratings
              ? " Backtest ratings are reconstructed from a copy of the production gates, which leaves out a few data checks, so they can be slightly more generous than the ratings the dashboard publishes."
              : ""}
          </p>
        ) : null}

        <section className="panel grid grid-cols-2 divide-border lg:grid-cols-4 lg:divide-x">
          <Tile
            label={`Top ${report.topN}`}
            value={headline}
            note={
              costs
                ? split
                  ? `after ${split.costsPct.toFixed(2)} pts of trading costs`
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
            note={
              report.universe.through && report.universe.through !== report.asOf
                ? `equal weight, daily; through ${formatDate(report.universe.through)}`
                : "equal weight, rebalanced daily"
            }
          />
          <Tile
            label={`Top ${report.topN} vs ${report.benchmark.name}`}
            value={excess}
            unit="pts"
            note="difference in return"
          />
          {split && headline !== null ? (
            <SplitRow split={split} total={headline} holdings={report.holdings.length} costs={costs} />
          ) : null}
        </section>

        <ReturnsChart
          basket={costs ? report.basket.curve : report.basket.grossCurve}
          benchmark={report.benchmark.curve}
          basketLabel={`Top ${report.topN}`}
          benchmarkLabel={report.benchmark.name}
          liveFrom={report.rankDate < report.liveFrom ? report.liveFrom : null}
        />

        <Portfolio
          holdings={report.holdings}
          trades={report.trades}
          closed={report.closed}
          market={market}
          topN={report.topN}
          lastRankDate={report.rebalance.lastRankDate}
          firstEntry={report.entrySession}
          rebalances={report.rebalance.count}
          swapped={report.rebalance.bought}
          costs={costs}
          split={split}
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

/**
 * The headline return taken apart: what was booked by selling, what is still
 * open on the holdings, and what trading cost. All three are points of the
 * starting capital, so they add up to the headline exactly -- the row is a
 * check on the number as much as a breakdown of it.
 *
 * Booked includes the trims: each rebalance cuts a winner back to equal
 * weight, which sells part of it and books that part's gain. So with frequent
 * rebalancing most of a return is booked long before a stock is sold outright.
 */
function SplitRow({
  split,
  total,
  holdings,
  costs,
}: {
  split: ReturnSplit;
  total: number;
  holdings: number;
  costs: boolean;
}) {
  return (
    <div className="col-span-full border-t px-4 py-3 sm:px-5">
      <dl className="flex flex-wrap items-end gap-x-3 gap-y-2">
        <SplitTerm label="Booked" value={split.bookedPct} note="on sales and trims" />
        <SplitSign>{split.openPct < 0 ? "−" : "+"}</SplitSign>
        <SplitTerm
          label="Open"
          value={Math.abs(split.openPct)}
          tone={split.openPct}
          note={`on ${holdings} ${holdings === 1 ? "holding" : "holdings"}, at the latest close`}
        />
        {costs ? (
          <>
            <SplitSign>−</SplitSign>
            <SplitTerm
              label="Costs"
              value={split.costsPct}
              tone={-1}
              note={`${split.paidPct.toFixed(2)} paid, the rest to sell today`}
            />
          </>
        ) : null}
        <SplitSign>=</SplitSign>
        <SplitTerm label="Return" value={total} unit="%" note="the headline" strong />
      </dl>
    </div>
  );
}

function SplitSign({ children }: { children: React.ReactNode }) {
  return (
    <span aria-hidden className="pb-4 text-sm text-muted-foreground">
      {children}
    </span>
  );
}

function SplitTerm({
  label,
  value,
  note,
  tone = value,
  unit = "pts",
  strong = false,
}: {
  label: string;
  value: number;
  note: string;
  tone?: number;
  unit?: "pts" | "%";
  strong?: boolean;
}) {
  const text =
    unit === "%"
      ? formatPercent(value, 2, true)
      : `${label === "Booked" && value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(2)} pts`;
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "numeral tabular text-sm leading-tight",
          strong ? "font-semibold" : "font-medium",
          tone >= 0 ? "text-positive" : "text-negative",
        )}
      >
        {text}
      </dd>
      <dd className="text-[11px] text-muted-foreground">{note}</dd>
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
