"use client";

import { useMemo, useState, useTransition } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ChevronRight } from "lucide-react";

import {
  BreadthChart,
  ScrubContext,
  formatDay,
  type ChartPoint,
  type ChartTone,
} from "@/components/market/breadth-chart";
import { ScrollFade } from "@/components/scroll-fade";
import { BreadthListSheet } from "@/components/market/breadth-list-sheet";
import { IndexChart } from "@/components/market/index-chart";
import { GroupPicker, type GroupKey } from "@/components/market/group-picker";
import { SegmentedControl } from "@/components/segmented-control";
import {
  RANGES,
  decodeRow,
  indexPoints,
  metricPoints,
  rangeStart,
  sliceFrom,
} from "@/lib/market-breadth.mjs";
import { marketPath, type Market } from "@/lib/markets";
import { liveOverlay, quoteFreshness } from "@/lib/live-quotes.mjs";
import type { BreadthGroup, BreadthRow } from "@/lib/queries";
import { useLiveQuotes, useNow } from "@/lib/use-live-quotes";
import { LIVE_DENOMINATORS, useLiveBreadth, type LiveBreadth } from "@/lib/use-live-breadth";
import { cn } from "@/lib/utils";

type Unit = "share" | "count";

type MetricSpec = { key: string; total: string; title: string; tone?: ChartTone };

const TREND: MetricSpec[] = [
  { key: "e20", total: "e20d", title: "Above 20-day EMA" },
  { key: "e50", total: "e50d", title: "Above 50-day EMA" },
  { key: "e100", total: "e100d", title: "Above 100-day EMA" },
  { key: "e200", total: "e200d", title: "Above 200-day EMA" },
];

const EXTREMES: MetricSpec[] = [
  { key: "hi", total: "hld", title: "New 52-week highs", tone: "positive" },
  { key: "lo", total: "hld", title: "New 52-week lows", tone: "negative" },
];

const LEADERSHIP: MetricSpec[] = [
  { key: "s2", total: "s2d", title: "In Stage 2" },
  { key: "bb", total: "bbd", title: "Beating the benchmark over 6 months" },
  { key: "rs", total: "rsd", title: "RS rating above 75" },
];

const DEFAULT_RANGE = "1Y";
const UNITS: readonly Unit[] = ["share", "count"];

/** URL keys that belong to the list view, cleared when it opens or closes. */
const LIST_KEYS = ["list", "sort", "dir", "page"];

export type BreadthList = {
  metric: string;
  total: number;
  /** The screener table and its pagination, rendered on the server. */
  content: React.ReactNode;
};

/**
 * The Market page: benchmark indices, then breadth for the selected group.
 *
 * Range, unit and the scrubbed date are client state -- changing them costs
 * no round trip, so they respond on the press. Range and unit are written to
 * the URL in place (`?range=3Y&unit=count`), so a reload or a shared link
 * keeps them, without asking the server for anything. The group is in the URL
 * as a navigation, because it selects which ~90 KB row the server sends; the
 * charts dim while that loads rather than blanking, so the page never jumps.
 */
export function MarketDashboard({
  market,
  groups,
  group,
  indices,
  selected,
  list,
  failed = false,
}: {
  market: Market;
  groups: BreadthGroup[];
  group: BreadthRow | null;
  indices: BreadthRow[];
  selected: GroupKey;
  list: BreadthList | null;
  /** A read failed, so what is missing is unknown rather than unpublished. */
  failed?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();
  const [, startListTransition] = useTransition();

  // Which list is open. Set on the press so the sheet rises immediately; the
  // URL, and with it the server's rows, follow. When the server's list
  // changes on its own -- Back, a shared link -- the sheet follows that.
  const serverList = list?.metric ?? null;
  const [openList, setOpenList] = useState<string | null>(serverList);
  const [seenServerList, setSeenServerList] = useState<string | null>(serverList);
  if (serverList !== seenServerList) {
    setSeenServerList(serverList);
    setOpenList(serverList);
  }
  // The last list shown, kept while the sheet slides away so it leaves with
  // its content rather than emptying first.
  const [lastList, setLastList] = useState<BreadthList | null>(list);
  if (list && list !== lastList) setLastList(list);

  const listUrl = (metric: string | null) => {
    const next = new URLSearchParams(searchParams.toString());
    for (const key of LIST_KEYS) next.delete(key);
    if (metric) next.set("list", metric);
    const query = next.toString();
    return query ? `${pathname}?${query}` : pathname;
  };
  const openListFor = (metric: string) => {
    setOpenList(metric);
    startListTransition(() => router.push(listUrl(metric), { scroll: false }));
  };
  const closeList = () => {
    setOpenList(null);
    startListTransition(() => router.push(listUrl(null), { scroll: false }));
  };
  const [range, setRangeState] = useState(() => {
    const asked = searchParams.get("range");
    return RANGES.some((entry) => entry.label === asked) ? asked! : DEFAULT_RANGE;
  });
  const [unit, setUnitState] = useState<Unit>(() => {
    const asked = searchParams.get("unit") as Unit | null;
    return asked && UNITS.includes(asked) ? asked : "share";
  });
  const [scrub, setScrub] = useState<string | null>(null);

  // In place, not a navigation: the server has nothing to add for a range or
  // a unit, and the history should not fill with every press.
  const remember = (key: "range" | "unit", value: string, fallback: string) => {
    const next = new URLSearchParams(window.location.search);
    if (value === fallback) next.delete(key);
    else next.set(key, value);
    const query = next.toString();
    window.history.replaceState(null, "", query ? `${pathname}?${query}` : pathname);
  };
  const setRange = (next: string) => {
    setRangeState(next);
    remember("range", next, DEFAULT_RANGE);
  };
  const setUnit = (next: Unit) => {
    setUnitState(next);
    remember("unit", next, "share");
  };

  const breadth = useMemo(() => decodeRow(group), [group]);
  const decodedIndices = useMemo(
    () =>
      indices
        .map((row) => ({ name: row.name, decoded: decodeRow(row) }))
        .filter((entry) => entry.decoded),
    [indices],
  );

  // Today's level for each charted index, every five minutes during the
  // session (workers/live_quotes.py), drawn as the chart's last point.
  const indexNames = useMemo(() => decodedIndices.map((entry) => entry.name), [decodedIndices]);
  const liveLevel = useLiveQuotes(market.code, indexNames, "index");
  const now = useNow();
  const liveQuotes = new Map(
    decodedIndices.map(({ name, decoded }) => [
      name,
      liveOverlay(liveLevel(name), decoded?.dates.at(-1)),
    ]),
  );
  let liveEnd = "";
  for (const quote of liveQuotes.values()) {
    if (quote && quote.session > liveEnd) liveEnd = quote.session;
  }

  // Today's breadth, counted from the same quotes against last night's
  // levels. Like an index's quote, it is drawn only for a session after the
  // published closes; once the evening run publishes that session, the
  // published point stands instead.
  const liveBreadth = useLiveBreadth(market.code, selected);
  const lastBreadthDay = breadth?.dates.at(-1);
  const breadthLive =
    liveBreadth?.counts && lastBreadthDay && liveBreadth.session > lastBreadthDay
      ? liveBreadth
      : null;
  if (breadthLive && breadthLive.session > liveEnd) liveEnd = breadthLive.session;
  const breadthFreshness = breadthLive
    ? quoteFreshness(breadthLive.fetched_at, breadthLive.traded_at, market, now)
    : null;

  // One x-domain for every chart, so a date sits at the same x everywhere
  // and the synced crosshair lines up down the page. A live session extends
  // it by a day, so today's point is on the plot.
  const { from, to } = useMemo(() => {
    const lasts = [breadth, ...decodedIndices.map((entry) => entry.decoded)]
      .map((decoded) => decoded?.dates.at(-1))
      .concat(liveEnd || undefined)
      .filter((date): date is string => Boolean(date));
    const firsts = [breadth, ...decodedIndices.map((entry) => entry.decoded)]
      .map((decoded) => decoded?.dates[0])
      .filter((date): date is string => Boolean(date));
    const end = lasts.sort().at(-1) ?? "";
    const entry = RANGES.find((item) => item.label === range);
    return {
      from: rangeStart(end, entry?.months ?? null, entry?.days ?? null) ?? firsts.sort()[0] ?? "",
      to: end,
    };
  }, [breadth, decodedIndices, range, liveEnd]);

  // Memoised as a whole so scrubbing -- which re-renders every chart to move
  // its crosshair -- hands each one the same arrays and its path is not
  // rebuilt on every pointer move.
  const metricSeries = useMemo(() => {
    const out: Record<string, ChartPoint[]> = {};
    if (!breadth) return out;
    for (const spec of [...TREND, ...EXTREMES, ...LEADERSHIP]) {
      const points = sliceFrom(metricPoints(breadth, spec.key, spec.total, unit), from);
      const today = livePoint(spec.key, breadthLive, unit);
      out[spec.key] = today ? [...points, today] : points;
    }
    return out;
  }, [breadth, unit, from, breadthLive]);
  // The live label, pulse and flash, for a chart whose last point is today's.
  const liveFor = (spec: MetricSpec) =>
    breadthLive && breadthFreshness && metricSeries[spec.key]?.at(-1)?.time === breadthLive.session
      ? {
          label: breadthFreshness.label,
          pulsing: breadthFreshness.state === "live",
          tick: breadthLive.ticks[spec.key] ?? null,
        }
      : undefined;
  const indexSeries = useMemo(
    () =>
      decodedIndices.map(({ name, decoded }) => ({
        name,
        points: sliceFrom(indexPoints(decoded), from) as ChartPoint[],
      })),
    [decodedIndices, from],
  );
  const series = (spec: MetricSpec) => metricSeries[spec.key] ?? [];
  // What each chart's change covers. "Max" is no span, so those charts name
  // the date they run from instead.
  const period = range === "Max" ? undefined : range;

  const select = (next: GroupKey) => {
    const params = new URLSearchParams();
    if (next.scope !== "market") params.set(next.scope, next.name);
    // A new group keeps the reader's range and unit.
    if (range !== DEFAULT_RANGE) params.set("range", range);
    if (unit !== "share") params.set("unit", unit);
    const query = params.toString();
    startTransition(() => {
      router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
    });
  };

  const filtered = selected.scope !== "market";
  const marketTotal = groups.find((entry) => entry.scope === "market")?.members ?? null;

  const leadership = leadershipSpecs(filtered, market.benchmark);

  // What the sheet shows. While a list loads, the count comes from the chart
  // itself -- the same number the reader just pressed on.
  const sheetKey = openList ?? lastList?.metric ?? null;
  const sheetSpec =
    leadership.find((entry) => entry.key === sheetKey) ??
    [...TREND, ...EXTREMES].find((entry) => entry.key === sheetKey);
  const sheetLoaded = openList !== null && list?.metric === openList;
  const sheetCount = sheetLoaded
    ? list.total
    : sheetKey
      ? (breadth?.series[sheetKey]?.at(-1) ?? null)
      : null;
  const lastDay = breadth?.dates.at(-1);
  const sheet = {
    title: sheetSpec?.title ?? "Stocks",
    detail: [
      sheetCount !== null ? `${sheetCount.toLocaleString(market.locale)} stocks` : null,
      filtered ? selected.name : `All ${market.label} stocks`,
      lastDay ? `as of ${formatDay(lastDay)}` : null,
    ]
      .filter(Boolean)
      .join(" · "),
    loaded: sheetLoaded,
    content: (sheetLoaded ? list : lastList)?.content ?? null,
  };

  return (
    <ScrubContext.Provider value={{ time: scrub, setTime: setScrub }}>
      {/* The controls change every chart below them, so from md they stay in
          reach: pinned under the top bar, which is two rows tall from md to
          xl and one from xl (components/app-shell.tsx). On a phone the bar
          would wrap to three lines and eat the screen, so it scrolls away. */}
      <div className="z-20 -mx-4 flex flex-wrap items-center gap-x-3 gap-y-2 bg-background px-4 py-2 sm:-mx-6 sm:px-6 md:sticky md:top-[6.3125rem] xl:top-[3.5625rem]">
        <GroupPicker
          groups={groups}
          selected={selected}
          total={marketTotal}
          onSelect={select}
        />
        <SegmentedControl<Unit>
          label="Measure"
          value={unit}
          onChange={setUnit}
          options={[
            { value: "share", label: "%", title: "Share of stocks" },
            { value: "count", label: "Count", title: "Number of stocks" },
          ]}
        />
        <div className="w-full sm:ml-auto sm:w-auto">
          <ScrollFade>
            <SegmentedControl
              label="Time range"
              value={range}
              onChange={setRange}
              options={RANGES.map((entry) => ({ value: entry.label, label: entry.label }))}
            />
          </ScrollFade>
        </div>
      </div>

      <div
        className={cn(
          "mt-4 space-y-10 transition-opacity duration-(--duration-base) ease-(--ease-standard)",
          pending && "pointer-events-none opacity-55",
        )}
        aria-busy={pending}
      >
        {decodedIndices.length ? (
          <Section
            title="Benchmark indices"
            action={
              <Link
                href={marketPath(market.slug, "/indices")}
                className="touch-target inline-flex h-7 shrink-0 items-center gap-0.5 rounded-md bg-(--control) pr-1.5 pl-2.5 text-xs font-medium text-muted-foreground transition-[background-color,color] duration-(--duration-fast) ease-(--ease-standard) hover:bg-(--control-hover) hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                All indices
                <ChevronRight className="size-3.5" aria-hidden />
              </Link>
            }
          >
            {indexSeries.map(({ name, points }) => (
              <IndexChart
                key={name}
                name={name}
                points={points}
                quote={liveQuotes.get(name) ?? null}
                market={market}
                now={now}
                from={from}
                to={to}
                period={period}
              />
            ))}
          </Section>
        ) : null}

        {breadth ? (
          <>
            <Section title="Trend participation">
              {TREND.map((spec) => (
                <BreadthChart
                  key={spec.key}
                  title={spec.title}
                  points={series(spec)}
                  from={from}
                  to={to}
                  period={period}
                  unit={unit}
                  locale={market.locale}
                  live={liveFor(spec)}
                  onExpand={() => openListFor(spec.key)}
                />
              ))}
            </Section>

            <Section title="Leadership">
              {leadership.map((spec, index) => (
                <div
                  key={spec.key}
                  className={cn(
                    "min-w-0",
                    leadership.length % 2 === 1 && index === leadership.length - 1 && "lg:col-span-2",
                  )}
                >
                  <BreadthChart
                    title={spec.title}
                    points={series(spec)}
                    from={from}
                    to={to}
                    period={period}
                    unit={unit}
                    locale={market.locale}
                    live={liveFor(spec)}
                  onExpand={() => openListFor(spec.key)}
                  />
                </div>
              ))}
            </Section>

            <Section title="52-week extremes">
              {EXTREMES.map((spec) => (
                <BreadthChart
                  key={spec.key}
                  title={spec.title}
                  points={series(spec)}
                  from={from}
                  to={to}
                  period={period}
                  unit={unit}
                  locale={market.locale}
                  tone={spec.tone}
                  live={liveFor(spec)}
                  onExpand={() => openListFor(spec.key)}
                />
              ))}
            </Section>
          </>
        ) : (
          <div className="panel px-5 py-12 text-center text-sm text-muted-foreground">
            {failed
              ? "Couldn\u2019t load breadth. Reload to retry."
              : filtered
                ? `No breadth for ${selected.name}. Try another group.`
                : "Breadth is published after the close."}
          </div>
        )}
      </div>

      <BreadthListSheet
        open={openList !== null}
        onClose={closeList}
        title={sheet.title}
        detail={sheet.detail}
        loading={openList !== null && !sheet.loaded}
      >
        {sheet.content}
      </BreadthListSheet>
    </ScrubContext.Provider>
  );
}

/**
 * Today's point for one metric, in the charts' unit, from the live counts --
 * or null for a metric with no live count (Stage 2, RS rating) or none
 * measured yet.
 */
function livePoint(key: string, live: LiveBreadth | null, unit: Unit): ChartPoint | null {
  const denominator = LIVE_DENOMINATORS[key];
  const count = live?.counts?.[key];
  const total = denominator ? live?.counts?.[denominator] : undefined;
  if (!live || count === undefined || !total || total <= 0) return null;
  return {
    time: live.session,
    value: unit === "share" ? (count / total) * 100 : count,
    count,
    total,
  };
}

/**
 * RS rating is a percentile of the whole market, so ~25% of all stocks clear
 * 75 on every day by construction. Only a slice of the market can move
 * against that, which is why its measure appears only when one is selected.
 */
function leadershipSpecs(filtered: boolean, benchmark: string): MetricSpec[] {
  return LEADERSHIP.filter((spec) => filtered || spec.key !== "rs").map((spec) =>
    spec.key === "bb" ? { ...spec, title: `Beating the ${benchmark} over 6 months` } : spec,
  );
}

function Section({
  title,
  action,
  children,
}: {
  title: string;
  /** A link beside the heading, e.g. to every index. */
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-4">
        <h2 className="text-lead font-semibold tracking-[-0.011em]">{title}</h2>
        {action}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">{children}</div>
    </section>
  );
}
