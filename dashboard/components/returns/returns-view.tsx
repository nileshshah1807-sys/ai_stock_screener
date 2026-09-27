"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useOptimistic, useState, useTransition } from "react";
import { Info } from "lucide-react";

import { ReturnsChart } from "@/components/returns/returns-chart";
import { Portfolio } from "@/components/returns/portfolio";
import { SegmentedControl } from "@/components/segmented-control";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Slider } from "@/components/ui/slider";
import { formatDate, formatPercent, MISSING } from "@/lib/format";
import { rangeStart } from "@/lib/market-breadth.mjs";
import type { Market } from "@/lib/markets";
import {
  COST_PER_SIDE_PCT,
  RATING_PICKS,
  REBALANCE_OPTIONS,
  STAGE_PICKS,
  START_PRESETS,
  INVESTED_OPTIONS,
  TOP_N_OPTIONS,
  WEIGHT_OPTIONS,
  modelForDate,
  pickOption,
  snapRankingDate,
} from "@/lib/returns.mjs";
import type { ReturnSplit, ReturnsReport } from "@/lib/returns-data";
import { cn } from "@/lib/utils";

type Report = Extract<ReturnsReport, { status: "ok" }>;

const CUSTOM = "custom";

type Shown = {
  from: string;
  top: string;
  rebalance: string;
  rating: string;
  stage: string;
  weights: string;
  invested: string;
};


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
  const reportPick = pickOption(report.pick);
  const [shown, setShown] = useOptimistic<Shown, Partial<Shown>>(
    {
      from: report.rankDate,
      top: String(report.topN),
      rebalance: report.rebalance.option,
      rating: reportPick.rating,
      stage: reportPick.stageFilter,
      weights: report.weights,
      invested: String(report.investedPct),
    },
    (current, patch) => ({ ...current, ...patch }),
  );

  const urlFor = (mutate: (params: URLSearchParams) => void) => {
    const next = new URLSearchParams(searchParams.toString());
    mutate(next);
    const query = next.toString();
    return query ? `${pathname}?${query}` : pathname;
  };
  const push = (patch: Partial<Shown>, mutate: (params: URLSearchParams) => void) => {
    const url = urlFor(mutate);
    startTransition(() => {
      setShown(patch);
      router.push(url, { scroll: false });
    });
  };
  // The two filters are written together, replacing the single `pick` of
  // older links, so changing one keeps the other.
  const setFilter = (patch: { rating?: string; stage?: string }) => {
    const next = { rating: shown.rating, stage: shown.stage, ...patch };
    push(patch, (params) => {
      params.delete("pick");
      for (const [name, value] of Object.entries(next)) {
        if (value === "all") params.delete(name);
        else params.set(name, value);
      }
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
  const pickPhrase = reportPick.phrase;
  const rounds = report.rebalance.count + 1;

  const holdRule = report.holds.length
    ? `Bought from the list, then held while it ${[
        report.holds.includes("buy_plus") ? "stays rated BUY or better" : null,
        report.holds.includes("advancing") ? "stays in Stage 2 or a pullback within it" : null,
      ]
        .filter(Boolean)
        .join(" and ")}; sold at the next rebalance after ${
        report.holds.length > 1
          ? "either breaks"
          : report.holds[0] === "advancing"
            ? "it breaks into Stage 3 or 4"
            : "its rating falls below that"
      }, not merely for leaving the list. Free slots are refilled from the list, best first.`
    : null;

  return (
    <div className="space-y-4">
      <section className="panel divide-y" aria-label="Portfolio settings">
        <ControlGroup title="What to buy">
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
            <Field label="Rating">
              <SegmentedControl
                label="Rating filter"
                value={shown.rating}
                onChange={(value) => setFilter({ rating: value })}
                options={RATING_PICKS.map(({ value, label, title }) => ({ value, label, title }))}
              />
            </Field>
            <Field label="Stage">
              <SegmentedControl
                label="Stage filter"
                value={shown.stage}
                onChange={(value) => setFilter({ stage: value })}
                options={STAGE_PICKS.map(({ value, label, title }) => ({ value, label, title }))}
              />
            </Field>
        </ControlGroup>
        <ControlGroup title="How to trade">
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
            {shown.rebalance !== "never" ? (
              <Field label="At each rebalance">
                <SegmentedControl
                  label="At each rebalance"
                  value={shown.weights}
                  onChange={(value) =>
                    push({ weights: value }, (params) =>
                      value === "equal" ? params.delete("weights") : params.set("weights", value),
                    )
                  }
                  options={WEIGHT_OPTIONS.map(({ value, label, title }) => ({ value, label, title }))}
                />
              </Field>
            ) : null}
            <Field label="Invested">
              <SegmentedControl
                label="Share of the money in the basket"
                value={shown.invested}
                onChange={(value) =>
                  push({ invested: value }, (params) =>
                    value === "100" ? params.delete("invested") : params.set("invested", value),
                  )
                }
                options={INVESTED_OPTIONS.map((pct) => ({ value: String(pct), label: `${pct}%` }))}
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
        </ControlGroup>
      </section>

      <div
        aria-busy={pending}
        className={cn(
          "space-y-4 transition-opacity duration-(--duration-fast) ease-(--ease-standard)",
          pending && "opacity-60 delay-150",
        )}
      >
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-sm max-sm:gap-x-3">
          <span className="font-semibold max-sm:w-full">
            Top {report.topN}
            {pickPhrase ? ` · ${pickPhrase}` : ""}
          </span>
          <Dot />
          <span className="tabular text-muted-foreground">
            {formatDate(report.entrySession)} → {formatDate(report.asOf)}
          </span>
          <Dot />
          <span className="text-muted-foreground">
            {rebalanceLabel
              ? `${report.rebalance.count} ${report.rebalance.count === 1 ? "rebalance" : "rebalances"}, ${report.rebalance.bought} swapped`
              : "bought once and held"}
          </span>
          {report.investedPct < 100 ? (
            <>
              <Dot />
              <span className="text-muted-foreground">
                {report.investedPct}% invested, {100 - report.investedPct}% in cash
              </span>
            </>
          ) : null}
          {report.backtestRounds ? (
            <span
              className="rounded-full border border-caution/40 bg-caution/10 px-2 py-0.5 text-[11px] font-medium text-caution"
              title="Built on backtest rankings over the period the model was fitted on"
            >
              {report.backtestRounds === rounds ? "Backtest" : "Mostly backtest"} · in-sample
            </span>
          ) : null}
          {report.shortRounds ? (
            <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
              Short on {report.shortRounds} of {rounds}
            </span>
          ) : null}
          <Popover>
            <PopoverTrigger
              aria-label="About this result"
              className="inline-flex size-7 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground active:scale-[0.94] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Info className="size-4" aria-hidden />
            </PopoverTrigger>
            <PopoverContent
              align="start"
              className="max-h-[70vh] w-[min(26rem,calc(100vw-2rem))] gap-3 overflow-y-auto p-4 text-xs leading-relaxed"
            >
              <Note title="This basket">
                The top {report.topN}
                {pickPhrase ? ` ${pickPhrase} stocks` : ""} of the {formatDate(report.rankDate)} ranking
                {report.model ? ` (${report.model})` : ""}, bought at the close on {formatDate(report.entrySession)}
                {rebalanceLabel && report.rebalance.count
                  ? `, rebuilt every ${rebalanceLabel} from the latest ranking${
                      lastModel && lastModel !== report.model ? ` (latest: ${lastModel})` : ""
                    }`
                  : ""}
                , and held for {sessionsHeld} {sessionsHeld === 1 ? "session" : "sessions"} to{" "}
                {formatDate(report.asOf)}.
              </Note>
              {holdRule || report.rebalance.count ? (
                <Note title="Buying and selling">
                  {holdRule ? `${holdRule} ` : ""}
                  {report.rebalance.count
                    ? report.weights === "equal"
                      ? "Every rebalance also resets each stock kept to an equal share, trimming winners and topping up losers."
                      : "A stock kept at a rebalance is left as bought, never trimmed or topped up; only money from sales buys new stocks."
                    : ""}
                </Note>
              ) : null}
              {report.investedPct < 100 ? (
                <Note title="Cash">
                  {report.investedPct}% of the money is in the basket and {100 - report.investedPct}% is kept as
                  cash, not invested and earning nothing. The split is restored at every rebalance by resizing the
                  whole basket.
                </Note>
              ) : null}
              {report.pickStartMovedFrom || report.shortRounds ? (
                <Note title="Gaps">
                  {report.pickStartMovedFrom
                    ? `The start moved from ${formatDate(report.pickStartMovedFrom)} to ${formatDate(report.rankDate)}: backtest ratings exist only from 2023, once filings carry enough fundamentals to rate. `
                    : ""}
                  {report.shortRounds
                    ? `On ${report.shortRounds === rounds ? "every" : `${report.shortRounds} of ${rounds}`} ${
                        rounds === 1 ? "purchase" : "rounds"
                      }, fewer than ${report.topN} stocks passed the pick; ${
                        report.weights === "equal"
                          ? "the basket held the ones that did in equal weight, and cash when none did."
                          : "the basket bought the ones that did and kept each empty slot’s share in cash."
                      }${reportPick.columns.length > 1 ? " Few stocks pass both filters at once." : ""}`
                    : ""}
                </Note>
              ) : null}
              {report.backtestRounds ? (
                <Note title="Backtest" tone="caution">
                  {report.backtestRounds === rounds
                    ? "Every ranking used here is"
                    : `${report.backtestRounds} of the ${rounds} rankings used here are`}{" "}
                  a point-in-time backtest, not one the dashboard published; published rankings begin{" "}
                  {formatDate(report.liveFrom)}. The model&rsquo;s weights were fitted on this same period, so these
                  returns are in-sample and flatter what to expect going forward.
                  {reportPick.ratings
                    ? " Backtest ratings come from a copy of the production gates that leaves out a few data checks, so they can be slightly more generous than published ones."
                    : ""}
                </Note>
              ) : null}
            </PopoverContent>
          </Popover>
          <span
            role="status"
            className={cn(
              "ml-auto text-xs text-muted-foreground transition-opacity duration-(--duration-fast)",
              pending ? "opacity-100 delay-150" : "opacity-0",
            )}
          >
            {pending ? "Updating…" : ""}
          </span>
        </div>

        <section className="panel grid grid-cols-2 divide-border lg:grid-cols-4 lg:divide-x">
          <Tile
            label={report.investedPct < 100 ? `Top ${report.topN}, ${report.investedPct}% invested` : `Top ${report.topN}`}
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
            <SplitRow
              split={split}
              total={headline}
              holdings={report.holdings.length}
              costs={costs}
              trims={report.weights === "equal" && report.rebalance.count > 0}
            />
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
 */
function SplitRow({
  split,
  total,
  holdings,
  costs,
  trims,
}: {
  split: ReturnSplit;
  total: number;
  holdings: number;
  costs: boolean;
  /** Equal-weight resets book gains by trimming, not only by selling. */
  trims: boolean;
}) {
  return (
    <div className="col-span-full border-t px-4 py-3 sm:px-5">
      {/* An equation on wider screens; on a phone it would wrap mid-sum, so
          it becomes a grid of signed figures instead. */}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:flex sm:flex-wrap sm:items-end sm:gap-x-3 sm:gap-y-2">
        <SplitTerm label="Booked" value={split.bookedPct} note={trims ? "on sales and trims" : "on stocks sold"} />
        <SplitSign>{split.openPct < 0 ? "−" : "+"}</SplitSign>
        <SplitTerm
          label="Open"
          value={Math.abs(split.openPct)}
          tone={split.openPct}
          signed={split.openPct}
          note={`on ${holdings} ${holdings === 1 ? "holding" : "holdings"}, at the latest close`}
        />
        {costs ? (
          <>
            <SplitSign>−</SplitSign>
            <SplitTerm
              label="Costs"
              value={split.costsPct}
              tone={-1}
              signed={-split.costsPct}
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
    <span aria-hidden className="pb-4 text-sm text-muted-foreground max-sm:hidden">
      {children}
    </span>
  );
}

function SplitTerm({
  label,
  value,
  note,
  tone = value,
  signed,
  unit = "pts",
  strong = false,
}: {
  label: string;
  value: number;
  note: string;
  tone?: number;
  /** The figure with its own sign, shown where the equation's operators are not. */
  signed?: number;
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
        {signed === undefined ? (
          text
        ) : (
          <>
            <span className="max-sm:hidden">{text}</span>
            <span className="sm:hidden">
              {signed > 0 ? "+" : signed < 0 ? "−" : ""}
              {Math.abs(signed).toFixed(2)} pts
            </span>
          </>
        )}
      </dd>
      <dd className="text-[11px] text-muted-foreground">{note}</dd>
    </div>
  );
}

/** One labelled row of the settings panel: a heading, then its controls. */
function ControlGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3 px-4 py-3 lg:flex-row lg:items-start lg:gap-6">
      <p className="w-24 shrink-0 text-xs font-semibold text-foreground lg:pt-0.5">{title}</p>
      <div className="flex min-w-0 flex-1 flex-wrap items-end gap-x-5 gap-y-3">{children}</div>
    </div>
  );
}

function Dot() {
  return (
    <span aria-hidden className="text-muted-foreground/60 max-sm:hidden">
      ·
    </span>
  );
}

function Note({
  title,
  tone,
  children,
}: {
  title: string;
  tone?: "caution";
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className={cn("mb-0.5 font-semibold", tone === "caution" ? "text-caution" : "text-foreground")}>{title}</p>
      <p className="text-muted-foreground">{children}</p>
    </div>
  );
}

/**
 * What each option of each control does, one line per option, behind the
 * control's own info button: the reader asks about the choice in front of
 * them, so the answer sits beside it rather than in a paragraph above.
 */
const CONTROL_HELP: Record<string, { term: string; text: string }[]> = {
  Start: [
    { term: "Start", text: "The ranking the basket is first bought from. A date with no ranking uses the latest one before it; the stocks are bought at the next session's close." },
  ],
  Basket: [{ term: "Top 10 / 20 / 50", text: "How many stocks the basket holds, bought in equal slices of the money." }],
  Rating: [
    { term: "All", text: "Any rating." },
    { term: "Buy+", text: "Buys only stocks rated BUY or STRONG BUY, and sells one once its rating falls below BUY." },
    { term: "Strong Buy", text: "Buys only STRONG BUY stocks, and keeps one while it stays BUY or better." },
  ],
  Stage: [
    { term: "All", text: "Any stage." },
    { term: "Stage 2", text: "Buys only stocks in a Stage 2 advance, keeps one through pullbacks, and sells it once it breaks into Stage 3 or 4." },
    { term: "Fresh S2", text: "Like Stage 2, but buys only advances that began within the last 30 days." },
    { term: "Both filters", text: "With a rating and a stage chosen, a stock must pass both to be bought, and is sold when it fails either." },
  ],
  Rebalance: [
    { term: "Never", text: "Bought once and held to today, whatever happens to the stocks." },
    { term: "1W to 3M", text: "How often the basket is checked: stocks that no longer qualify are sold, and the free slots refilled from the latest ranking." },
  ],
  "At each rebalance": [
    { term: "Hold as bought", text: "A stock that is kept is left alone. Only the money from sales buys new stocks, so winners are left to run and grow into a bigger share." },
    { term: "Reset to equal", text: "Every rebalance also trims each winner and tops up each loser back to an equal share. It takes profits and buys dips each time, and pays more in costs." },
  ],
  Invested: [
    { term: "100%", text: "All the money is in the basket." },
    {
      term: "80% / 60% / 40%",
      text: "Only that share is in the basket; the rest is kept as cash in the account, not invested and earning nothing. Every rebalance restores the split by resizing the whole basket. A crash then hits only the invested share: at 60%, a 48% fall in the basket is about a 29% fall overall, and good years earn less in the same proportion.",
    },
  ],
  Costs: [
    { term: `${COST_PER_SIDE_PCT}% a side`, text: "Brokerage, taxes and slippage on every purchase and sale, including selling everything today." },
    { term: "None", text: "Returns before any trading costs." },
  ],
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  const help = CONTROL_HELP[label];
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        {help ? (
          <Popover>
            <PopoverTrigger
              aria-label={`About ${label}`}
              className="inline-flex size-5 items-center justify-center rounded-full text-muted-foreground/70 transition-colors hover:bg-muted hover:text-foreground active:scale-[0.94] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Info className="size-3.5" aria-hidden />
            </PopoverTrigger>
            <PopoverContent align="start" className="w-[min(20rem,calc(100vw-2rem))] p-3 text-xs leading-relaxed">
              <dl className="space-y-2">
                {help.map((item) => (
                  <div key={item.term}>
                    <dt className="font-semibold text-foreground">{item.term}</dt>
                    <dd className="text-muted-foreground">{item.text}</dd>
                  </div>
                ))}
              </dl>
            </PopoverContent>
          </Popover>
        ) : null}
      </div>
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
