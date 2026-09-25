"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { niceScale, pointAt, timeTicks, timeValue } from "@/lib/market-breadth.mjs";
import { cn } from "@/lib/utils";

/**
 * Cumulative return of the basket against its benchmark, in SVG.
 *
 * Built on the Market page's chart helpers (`niceScale`, `timeTicks`,
 * `pointAt`) rather than on lightweight-charts: two lines and a zero rule is
 * all this needs, and the header-readout pattern -- values at the hovered date
 * where the eye already is, no floating tooltip -- matches `BreadthChart`.
 */

export type ReturnPoint = { time: string; value: number };

const HEIGHT = 240;
const PAD = { top: 12, right: 52, bottom: 22, left: 2 };

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function signed(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(2)}%`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "18 Sep 2026", matching BreadthChart. */
function formatDay(time: string) {
  const [year, month, day] = time.split("-");
  return `${Number(day)} ${MONTHS[Number(month) - 1]} ${year}`;
}

export function ReturnsChart({
  basket,
  benchmark,
  basketLabel,
  benchmarkLabel,
}: {
  basket: ReturnPoint[];
  benchmark: ReturnPoint[];
  basketLabel: string;
  benchmarkLabel: string;
}) {
  const [container, width] = useWidth();
  const [hover, setHover] = useState<string | null>(null);

  const plotW = Math.max(0, width - PAD.left - PAD.right);
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const from = basket[0]?.time ?? benchmark[0]?.time ?? "";
  const to = basket.at(-1)?.time ?? benchmark.at(-1)?.time ?? "";

  const geometry = useMemo(() => {
    if (!basket.length || plotW <= 0) return null;
    const x0 = timeValue(from);
    const x1 = Math.max(timeValue(to), x0 + 1);
    let min = 0;
    let max = 0;
    for (const point of [...basket, ...benchmark]) {
      if (point.value < min) min = point.value;
      if (point.value > max) max = point.value;
    }
    const scale = niceScale(min, max, { count: 4 });
    const x = (time: string) => PAD.left + ((timeValue(time) - x0) / (x1 - x0)) * plotW;
    const y = (value: number) =>
      PAD.top + plotH - ((value - scale.min) / (scale.max - scale.min || 1)) * plotH;
    const path = (points: ReturnPoint[]) =>
      points
        .map((point, index) => `${index === 0 ? "M" : "L"}${x(point.time).toFixed(1)},${y(point.value).toFixed(1)}`)
        .join("");
    return { x, y, scale, x0, x1, basketLine: path(basket), benchmarkLine: path(benchmark) };
  }, [basket, benchmark, from, to, plotW, plotH]);

  const ticks = useMemo(() => timeTicks(from, to, width < 420 ? 4 : 6), [from, to, width]);

  const shownTime = hover ?? to;
  const basketShown = shownTime ? pointAt(basket, shownTime) : null;
  const benchmarkShown = shownTime ? pointAt(benchmark, shownTime) : null;

  const onPointer = (event: React.PointerEvent<SVGRectElement>) => {
    if (!geometry || !basket.length) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const target = geometry.x0 + ratio * (geometry.x1 - geometry.x0);
    let best = basket[0];
    for (const point of basket) {
      if (Math.abs(timeValue(point.time) - target) < Math.abs(timeValue(best.time) - target)) best = point;
    }
    setHover(best.time);
  };

  const label = basket.length
    ? `${basketLabel} ${signed(basket.at(-1)!.value)} against ${benchmarkLabel} ${signed(
        benchmark.at(-1)?.value,
      )}, ${formatDay(from)} to ${formatDay(to)}.`
    : "No returns to chart.";

  return (
    <section className="panel flex min-w-0 flex-col p-4 sm:p-5">
      <header className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
        <Legend tone="basket" label={basketLabel} value={basketShown?.value} />
        <Legend tone="benchmark" label={benchmarkLabel} value={benchmarkShown?.value} />
        <span className="tabular ml-auto text-xs text-muted-foreground">
          {shownTime ? formatDay(shownTime) : null}
        </span>
      </header>

      <div ref={container} className="relative mt-3 w-full" style={{ height: HEIGHT }}>
        {geometry ? (
          <svg width={width} height={HEIGHT} role="img" aria-label={label} className="block overflow-visible select-none">
            {geometry.scale.ticks.map((tick) => (
              <g key={tick}>
                <line
                  x1={PAD.left}
                  x2={PAD.left + plotW}
                  y1={geometry.y(tick)}
                  y2={geometry.y(tick)}
                  stroke="var(--border)"
                  strokeOpacity={tick === 0 ? 1 : 0.7}
                  strokeDasharray={tick === 0 ? "3 4" : undefined}
                />
                <text
                  x={PAD.left + plotW + 8}
                  y={geometry.y(tick)}
                  dy="0.32em"
                  className="fill-muted-foreground text-[0.6875rem] tabular"
                >
                  {`${tick > 0 ? "+" : ""}${tick}%`}
                </text>
              </g>
            ))}

            {ticks.map((tick) => {
              const at = geometry.x(tick.time);
              if (at < PAD.left + 12 || at > PAD.left + plotW - 12) return null;
              return (
                <text
                  key={tick.time}
                  x={at}
                  y={HEIGHT - 4}
                  textAnchor="middle"
                  className="fill-muted-foreground text-[0.6875rem]"
                >
                  {tick.label}
                </text>
              );
            })}

            <path
              d={geometry.benchmarkLine}
              fill="none"
              stroke="var(--muted-foreground)"
              strokeWidth={1.5}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            <path
              d={geometry.basketLine}
              fill="none"
              stroke="var(--chart-line)"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />

            {hover && basketShown ? (
              <g aria-hidden>
                <line
                  x1={geometry.x(basketShown.time)}
                  x2={geometry.x(basketShown.time)}
                  y1={PAD.top}
                  y2={PAD.top + plotH}
                  stroke="var(--foreground)"
                  strokeOpacity={0.35}
                />
                {benchmarkShown ? (
                  <circle
                    cx={geometry.x(benchmarkShown.time)}
                    cy={geometry.y(benchmarkShown.value)}
                    r={3.5}
                    fill="var(--muted-foreground)"
                    stroke="var(--card)"
                    strokeWidth={2}
                  />
                ) : null}
                <circle
                  cx={geometry.x(basketShown.time)}
                  cy={geometry.y(basketShown.value)}
                  r={4}
                  fill="var(--chart-line)"
                  stroke="var(--card)"
                  strokeWidth={2}
                />
              </g>
            ) : null}

            <rect
              x={PAD.left}
              y={0}
              width={plotW}
              height={HEIGHT}
              fill="transparent"
              style={{ touchAction: "pan-y" }}
              onPointerMove={onPointer}
              onPointerDown={onPointer}
              onPointerLeave={() => setHover(null)}
              onPointerCancel={() => setHover(null)}
            />
          </svg>
        ) : null}
      </div>
    </section>
  );
}

function Legend({
  tone,
  label,
  value,
}: {
  tone: "basket" | "benchmark";
  label: string;
  value: number | null | undefined;
}) {
  return (
    <span className="inline-flex items-baseline gap-2">
      <span
        aria-hidden
        className={cn(
          "inline-block h-0.5 w-3 translate-y-[-0.2rem] rounded-full",
          tone === "basket" ? "bg-(--chart-line)" : "bg-muted-foreground",
        )}
      />
      <span className="text-xs text-muted-foreground">{label}</span>
      <span
        className={cn(
          "tabular text-sm font-semibold",
          value === null || value === undefined ? "text-muted-foreground" : value >= 0 ? "text-positive" : "text-negative",
        )}
      >
        {signed(value)}
      </span>
    </span>
  );
}
