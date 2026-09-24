"use client";

import { useMemo, useState, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { BreadthChart, ScrubContext, type ChartPoint, type ChartTone } from "@/components/market/breadth-chart";
import { BreadthListSheet } from "@/components/market/breadth-list-sheet";
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
import type { Market } from "@/lib/markets";
import type { BreadthGroup, BreadthRow } from "@/lib/queries";
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
 * no round trip, so they respond on the press. Only the group is in the URL,
 * because it selects which ~90 KB row the server sends; the charts dim while
 * that loads rather than blanking, so the page never jumps.
 */
export function MarketDashboard({
  market,
  groups,
  group,
  indices,
  selected,
  list,
}: {
  market: Market;
  groups: BreadthGroup[];
  group: BreadthRow | null;
  indices: BreadthRow[];
  selected: GroupKey;
  list: BreadthList | null;
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
  const [range, setRange] = useState(DEFAULT_RANGE);
  const [unit, setUnit] = useState<Unit>("share");
  const [scrub, setScrub] = useState<string | null>(null);

  const breadth = useMemo(() => decodeRow(group), [group]);
  const decodedIndices = useMemo(
    () =>
      indices
        .map((row) => ({ name: row.name, decoded: decodeRow(row) }))
        .filter((entry) => entry.decoded),
    [indices],
  );

  // One x-domain for every chart, so a date sits at the same x everywhere
  // and the synced crosshair lines up down the page.
  const { from, to } = useMemo(() => {
    const lasts = [breadth, ...decodedIndices.map((entry) => entry.decoded)]
      .map((decoded) => decoded?.dates.at(-1))
      .filter((date): date is string => Boolean(date));
    const firsts = [breadth, ...decodedIndices.map((entry) => entry.decoded)]
      .map((decoded) => decoded?.dates[0])
      .filter((date): date is string => Boolean(date));
    const end = lasts.sort().at(-1) ?? "";
    const months = RANGES.find((entry) => entry.label === range)?.months ?? null;
    return { from: rangeStart(end, months) ?? firsts.sort()[0] ?? "", to: end };
  }, [breadth, decodedIndices, range]);

  // Memoised as a whole so scrubbing -- which re-renders every chart to move
  // its crosshair -- hands each one the same arrays and its path is not
  // rebuilt on every pointer move.
  const metricSeries = useMemo(() => {
    const out: Record<string, ChartPoint[]> = {};
    if (!breadth) return out;
    for (const spec of [...TREND, ...EXTREMES, ...LEADERSHIP]) {
      out[spec.key] = sliceFrom(metricPoints(breadth, spec.key, spec.total, unit), from);
    }
    return out;
  }, [breadth, unit, from]);
  const indexSeries = useMemo(
    () =>
      decodedIndices.map(({ name, decoded }) => ({
        name,
        points: sliceFrom(indexPoints(decoded), from) as ChartPoint[],
      })),
    [decodedIndices, from],
  );
  const series = (spec: MetricSpec) => metricSeries[spec.key] ?? [];

  const select = (next: GroupKey) => {
    const params = new URLSearchParams();
    if (next.scope !== "market") params.set(next.scope, next.name);
    const query = params.toString();
    startTransition(() => {
      router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
    });
  };

  const filtered = selected.scope !== "market";
  const marketTotal = groups.find((entry) => entry.scope === "market")?.members ?? null;

  // RS rating is a percentile of the whole market, so ~25% of all stocks
  // clear 75 on every day by construction. Only a slice of the market can
  // move against that, which is why the chart appears only when one is
  // selected.
  const leadership = LEADERSHIP.filter((spec) => filtered || spec.key !== "rs").map((spec) =>
    spec.key === "bb" ? { ...spec, title: `Beating the ${market.benchmark} over 6 months` } : spec,
  );

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
      lastDay ? `as of ${formatListDay(lastDay)}` : null,
    ]
      .filter(Boolean)
      .join(" · "),
    loaded: sheetLoaded,
    content: (sheetLoaded ? list : lastList)?.content ?? null,
  };

  return (
    <ScrubContext.Provider value={{ time: scrub, setTime: setScrub }}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
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
          <div className="max-w-full overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <SegmentedControl
              label="Time range"
              value={range}
              onChange={setRange}
              options={RANGES.map((entry) => ({ value: entry.label, label: entry.label }))}
            />
          </div>
        </div>
      </div>

      <div
        className={cn(
          "mt-6 space-y-10 transition-opacity duration-(--duration-base) ease-(--ease-standard)",
          pending && "pointer-events-none opacity-55",
        )}
        aria-busy={pending}
      >
        {decodedIndices.length ? (
          <Section title="Benchmark indices" description="Where the headline indices are trading.">
            {indexSeries.map(({ name, points }) => (
              <BreadthChart
                key={name}
                title={name}
                points={points}
                from={from}
                to={to}
                unit="level"
                locale={market.locale}
              />
            ))}
          </Section>
        ) : null}

        {breadth ? (
          <>
            <Section
              title="Trend participation"
              description={`${subject(selected, market)} closing above each exponential moving average.`}
            >
              {TREND.map((spec) => (
                <BreadthChart
                  key={spec.key}
                  title={spec.title}
                  points={series(spec)}
                  from={from}
                  to={to}
                  unit={unit}
                  locale={market.locale}
                  onExpand={() => openListFor(spec.key)}
                />
              ))}
            </Section>

            <Section
              title="Leadership"
              description={
                filtered
                  ? `Stage 2 uptrends, stocks outpacing the ${market.benchmark}, and stocks the whole market ranks in its top quarter for relative strength.`
                  : `Stocks in a Stage 2 uptrend, and stocks outpacing the ${market.benchmark} over six months.`
              }
            >
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
                    unit={unit}
                    locale={market.locale}
                    onExpand={() => openListFor(spec.key)}
                  />
                </div>
              ))}
            </Section>

            <Section title="52-week extremes" description="Stocks closing at a new one-year high or low.">
              {EXTREMES.map((spec) => (
                <BreadthChart
                  key={spec.key}
                  title={spec.title}
                  points={series(spec)}
                  from={from}
                  to={to}
                  unit={unit}
                  locale={market.locale}
                  tone={spec.tone}
                  onExpand={() => openListFor(spec.key)}
                />
              ))}
            </Section>
          </>
        ) : (
          <div className="panel px-5 py-12 text-center">
            <p className="text-sm font-medium">
              {filtered
                ? `No breadth history is published for ${selected.name}.`
                : `Market breadth has not been published for ${market.label} yet.`}
            </p>
            <p className="mx-auto mt-1 max-w-md text-xs text-muted-foreground">
              {filtered
                ? "It may have too few stocks to chart, or have left the universe. Choose another group."
                : "It is rebuilt every trading day after the close."}
            </p>
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

const LIST_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function formatListDay(time: string) {
  const [year, month, day] = time.split("-");
  return `${Number(day)} ${LIST_MONTHS[Number(month) - 1]} ${year}`;
}

function subject(selected: GroupKey, market: Market) {
  return selected.scope === "market" ? `${market.label} stocks` : `${selected.name} stocks`;
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="mb-3">
        <h2 className="text-lead font-semibold tracking-[-0.011em]">{title}</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">{children}</div>
    </section>
  );
}
