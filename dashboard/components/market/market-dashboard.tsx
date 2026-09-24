"use client";

import { useMemo, useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";

import { BreadthChart, ScrubContext, type ChartPoint, type ChartTone } from "@/components/market/breadth-chart";
import { GroupPicker, type GroupKey } from "@/components/market/group-picker";
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
}: {
  market: Market;
  groups: BreadthGroup[];
  group: BreadthRow | null;
  indices: BreadthRow[];
  selected: GroupKey;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();
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

  return (
    <ScrubContext.Provider value={{ time: scrub, setTime: setScrub }}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <GroupPicker
          groups={groups}
          selected={selected}
          total={marketTotal}
          onSelect={select}
        />
        <Segmented
          label="Measure"
          value={unit}
          onChange={(value) => setUnit(value as Unit)}
          options={[
            { value: "share", label: "%", title: "Share of stocks" },
            { value: "count", label: "Count", title: "Number of stocks" },
          ]}
        />
        <div className="w-full sm:ml-auto sm:w-auto">
          <div className="max-w-full overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <Segmented
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
    </ScrubContext.Provider>
  );
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

/**
 * A small segmented control. The selected segment is a raised lens on a
 * recessed track, and it changes on pointer-down so the press is answered
 * before the click completes.
 */
function Segmented({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string; title?: string }[];
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex w-max rounded-full bg-(--control) p-0.5">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            title={option.title}
            onPointerDown={(event) => {
              if (event.button === 0) onChange(option.value);
            }}
            onClick={() => onChange(option.value)}
            className={cn(
              "inline-flex h-8 min-w-10 items-center justify-center rounded-full px-3 text-[0.8125rem]",
              "transition-[color,background-color,box-shadow,transform] duration-(--duration-base) ease-(--ease-standard)",
              "active:scale-[0.95] active:duration-(--duration-press)",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              active
                ? "lens font-semibold text-foreground"
                : "font-medium text-muted-foreground hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
