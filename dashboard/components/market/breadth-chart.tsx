"use client";

import { createContext, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";

import {
  niceScale,
  pointAt,
  timeTicks,
  timeValue,
} from "@/lib/market-breadth.mjs";
import { cn } from "@/lib/utils";

/**
 * One time series on the Market page, drawn in SVG.
 *
 * SVG rather than lightweight-charts because the page shows a dozen of these
 * at once and they must scrub together: a canvas chart per card would mean a
 * dozen chart instances and a dozen crosshair APIs to keep in step, where here
 * one shared date in context moves every crosshair in the same frame.
 *
 * The header works the way Apple's Stocks app does. At rest it shows the
 * latest value and its change over the visible range; while the pointer is on
 * any chart it shows the value on the hovered date instead, so scrubbing one
 * chart reads the whole page at that date. There is no floating tooltip to
 * chase the pointer -- the number lives where the eye already is.
 */

export type ChartPoint = { time: string; value: number; count?: number; total?: number };

export type ChartUnit = "share" | "count" | "level";

type Scrub = { time: string | null; setTime: (time: string | null) => void };

export const ScrubContext = createContext<Scrub>({ time: null, setTime: () => {} });

const HEIGHT = 168;
const PAD = { top: 10, right: 52, bottom: 22, left: 2 };

const TONES = {
  accent: "var(--chart-line)",
  positive: "var(--positive)",
  negative: "var(--negative)",
} as const;

export type ChartTone = keyof typeof TONES;

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

export function BreadthChart({
  title,
  points,
  from,
  to,
  unit,
  locale,
  tone = "accent",
}: {
  title: string;
  points: ChartPoint[];
  /** Shared x-domain, so every chart on the page lines up by date. */
  from: string;
  to: string;
  unit: ChartUnit;
  locale: string;
  tone?: ChartTone;
}) {
  const { time: scrubTime, setTime } = useContext(ScrubContext);
  const [container, width] = useWidth();
  // useId can contain characters that are not valid in a url(#id) reference.
  const gradientId = `fill-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const color = TONES[tone];

  const plotW = Math.max(0, width - PAD.left - PAD.right);
  const plotH = HEIGHT - PAD.top - PAD.bottom;

  const format = useMemo(() => formatter(unit, locale), [unit, locale]);

  const geometry = useMemo(() => {
    if (!points.length || plotW <= 0) return null;
    const x0 = timeValue(from);
    const x1 = Math.max(timeValue(to), x0 + 1);
    let min = Infinity;
    let max = -Infinity;
    for (const point of points) {
      if (point.value < min) min = point.value;
      if (point.value > max) max = point.value;
    }
    const scale = niceScale(min, max, {
      count: 4,
      clamp: unit === "share" ? [0, 100] : unit === "count" ? [0, Infinity] : undefined,
    });
    const x = (time: string) => PAD.left + ((timeValue(time) - x0) / (x1 - x0)) * plotW;
    const y = (value: number) =>
      PAD.top + plotH - ((value - scale.min) / (scale.max - scale.min || 1)) * plotH;

    let line = "";
    for (let index = 0; index < points.length; index += 1) {
      const point = points[index];
      line += `${index === 0 ? "M" : "L"}${x(point.time).toFixed(1)},${y(point.value).toFixed(1)}`;
    }
    const first = points[0];
    const last = points[points.length - 1];
    const area = `${line}L${x(last.time).toFixed(1)},${PAD.top + plotH}L${x(first.time).toFixed(1)},${PAD.top + plotH}Z`;
    return { x, y, scale, line, area, x0, x1 };
  }, [points, from, to, unit, plotW, plotH]);

  const ticks = useMemo(
    () => timeTicks(from, to, width < 420 ? 4 : 6),
    [from, to, width],
  );

  const latest = points[points.length - 1] ?? null;
  const hovered = scrubTime ? pointAt(points, scrubTime) : null;
  const shown = hovered ?? latest;
  const base = points[0] ?? null;

  const onPointer = (event: React.PointerEvent<SVGRectElement>) => {
    if (!geometry || !points.length) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const target = geometry.x0 + ratio * (geometry.x1 - geometry.x0);
    // Nearest point by date, so the crosshair snaps to a real session.
    let low = 0;
    let high = points.length - 1;
    while (low < high) {
      const mid = (low + high) >> 1;
      if (timeValue(points[mid].time) < target) low = mid + 1;
      else high = mid;
    }
    const candidate =
      low > 0 && Math.abs(timeValue(points[low - 1].time) - target) < Math.abs(timeValue(points[low].time) - target)
        ? points[low - 1]
        : points[low];
    setTime(candidate.time);
  };

  const label = latest
    ? `${title}: ${format(latest.value)} on ${formatDay(latest.time)}${
        base && base !== latest ? `, from ${format(base.value)} on ${formatDay(base.time)}` : ""
      }.`
    : `${title}: no data in this range.`;

  return (
    <section className="panel flex min-w-0 flex-col p-4 sm:p-5">
      <header className="min-h-[4.75rem]">
        <h3 className="text-[0.8125rem] font-medium text-muted-foreground">{title}</h3>
        {shown ? (
          <>
            <div className="mt-0.5 flex flex-wrap items-baseline gap-x-2">
              <span className="numeral text-[1.625rem] leading-tight font-semibold tracking-[-0.02em]">
                {format(shown.value)}
              </span>
              {base && shown !== base ? (
                <Change from={base.value} to={shown.value} unit={unit} locale={locale} />
              ) : null}
            </div>
            <p className="tabular mt-0.5 truncate text-xs text-muted-foreground">
              {shown.count !== undefined && shown.total !== undefined
                ? `${shown.count.toLocaleString(locale)} of ${shown.total.toLocaleString(locale)} · `
                : ""}
              {formatDay(shown.time)}
            </p>
          </>
        ) : (
          <p className="mt-2 text-sm text-muted-foreground">Nothing measured in this range.</p>
        )}
      </header>

      <div ref={container} className="relative mt-3 w-full" style={{ height: HEIGHT }}>
        {geometry ? (
          <svg
            width={width}
            height={HEIGHT}
            role="img"
            aria-label={label}
            className="block overflow-visible select-none"
          >
            <defs>
              <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.22} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>

            {geometry.scale.ticks.map((tick) => (
              <g key={tick}>
                <line
                  x1={PAD.left}
                  x2={PAD.left + plotW}
                  y1={geometry.y(tick)}
                  y2={geometry.y(tick)}
                  stroke="var(--border)"
                  strokeOpacity={0.7}
                  strokeDasharray={unit === "share" && tick === 50 ? "3 4" : undefined}
                />
                <text
                  x={PAD.left + plotW + 8}
                  y={geometry.y(tick)}
                  dy="0.32em"
                  className="fill-muted-foreground text-[0.6875rem] tabular"
                >
                  {axisFormat(tick, unit, locale)}
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

            <path d={geometry.area} fill={`url(#${gradientId})`} />
            <path
              d={geometry.line}
              fill="none"
              stroke={color}
              strokeWidth={1.75}
              strokeLinejoin="round"
              strokeLinecap="round"
            />

            {hovered ? (
              <g aria-hidden>
                <line
                  x1={geometry.x(hovered.time)}
                  x2={geometry.x(hovered.time)}
                  y1={PAD.top}
                  y2={PAD.top + plotH}
                  stroke="var(--foreground)"
                  strokeOpacity={0.35}
                />
                <circle
                  cx={geometry.x(hovered.time)}
                  cy={geometry.y(hovered.value)}
                  r={4}
                  fill={color}
                  stroke="var(--card)"
                  strokeWidth={2}
                />
              </g>
            ) : latest ? (
              <circle
                aria-hidden
                cx={geometry.x(latest.time)}
                cy={geometry.y(latest.value)}
                r={3}
                fill={color}
                stroke="var(--card)"
                strokeWidth={2}
              />
            ) : null}

            {/* The hit area covers the plot, not just the line, and pans
                vertically so a finger can still scroll the page past it. */}
            <rect
              x={PAD.left}
              y={0}
              width={plotW}
              height={HEIGHT}
              fill="transparent"
              style={{ touchAction: "pan-y" }}
              onPointerMove={onPointer}
              onPointerDown={onPointer}
              onPointerLeave={() => setTime(null)}
              onPointerCancel={() => setTime(null)}
            />
          </svg>
        ) : null}
      </div>
    </section>
  );
}

function Change({
  from,
  to,
  unit,
  locale,
}: {
  from: number;
  to: number;
  unit: ChartUnit;
  locale: string;
}) {
  const diff = to - from;
  if (!Number.isFinite(diff)) return null;
  // A share moves in percentage points; an index level in percent of itself.
  const text =
    unit === "share"
      ? `${diff >= 0 ? "+" : "−"}${Math.abs(diff).toFixed(1)} pts`
      : unit === "count"
        ? `${diff >= 0 ? "+" : "−"}${Math.abs(Math.round(diff)).toLocaleString(locale)}`
        : from > 0
          ? `${diff >= 0 ? "+" : "−"}${Math.abs((diff / from) * 100).toFixed(1)}%`
          : null;
  if (!text) return null;
  const flat = Math.abs(diff) < 1e-9;
  const up = diff > 0;
  return (
    <span
      className={cn(
        "tabular inline-flex items-center gap-0.5 text-xs font-medium",
        flat ? "text-muted-foreground" : up ? "text-positive" : "text-negative",
      )}
    >
      {flat ? null : up ? (
        <ArrowUpRight className="size-3" aria-hidden />
      ) : (
        <ArrowDownRight className="size-3" aria-hidden />
      )}
      {text}
    </span>
  );
}

function formatter(unit: ChartUnit, locale: string) {
  if (unit === "share") return (value: number) => `${value.toFixed(1)}%`;
  if (unit === "count") return (value: number) => Math.round(value).toLocaleString(locale);
  return (value: number) =>
    value.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function axisFormat(value: number, unit: ChartUnit, locale: string) {
  if (unit === "share") return `${value}%`;
  return value.toLocaleString(locale, { maximumFractionDigits: value < 10 ? 1 : 0 });
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "18 Sep 2026". Built by hand: en-GB now abbreviates September as "Sept". */
function formatDay(time: string) {
  const [year, month, day] = time.split("-");
  return `${Number(day)} ${MONTHS[Number(month) - 1]} ${year}`;
}
