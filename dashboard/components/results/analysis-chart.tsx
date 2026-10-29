"use client";

import { useEffect, useRef, useState } from "react";

import { niceScale } from "@/lib/market-breadth.mjs";

/**
 * Median growth per quarter, three bars to a quarter, drawn in SVG like the
 * Market page's charts (`components/market/breadth-chart.tsx`).
 *
 * Every bar carries its figure and its quarter says how many results it
 * rests on, so nothing is read off an axis; a bar with no figure (no company
 * had a rate) is a dash on the baseline, not a zero. Hover or focus names the
 * median and the companies behind it. Below a width that fits the labels the
 * chart scrolls sideways rather than shrinking its type.
 */

export type AnalysisColumn = {
  label: string;
  results: number;
  /** One per series, in order; `n` is the companies the median rests on. */
  values: { median: number | null; n: number }[];
};

export type AnalysisSeries = { key: string; label: string; color: string };

const HEIGHT = 340;
const PAD = { top: 22, right: 8, bottom: 46, left: 40 };
const MIN_COLUMN = 160;
/** Bars sit this far apart; a label is about as wide as a bar, so they must not crowd. */
const GAP = 6;

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

export function AnalysisChart({
  columns,
  series,
}: {
  columns: AnalysisColumn[];
  series: AnalysisSeries[];
}) {
  const [container, measured] = useWidth();
  const width = Math.max(measured, columns.length * MIN_COLUMN + PAD.left + PAD.right);
  const medians = columns.flatMap((column) => column.values.map((value) => value.median));
  const known = medians.filter((value): value is number => value !== null);
  const scale = niceScale(Math.min(0, ...known), Math.max(0, ...known));
  const plotWidth = width - PAD.left - PAD.right;
  const plotHeight = HEIGHT - PAD.top - PAD.bottom;
  const y = (value: number) => PAD.top + ((scale.max - value) / (scale.max - scale.min)) * plotHeight;
  const group = plotWidth / columns.length;
  const bar = Math.min(44, (group * 0.8) / series.length - GAP);
  const zero = y(0);

  return (
    <figure className="space-y-3">
      <figcaption className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {series.map((item) => (
          <span key={item.key} className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-full" style={{ background: item.color }} aria-hidden />
            Median {item.label} growth YoY
          </span>
        ))}
      </figcaption>
      <div ref={container} className="overflow-x-auto">
        {measured ? (
          <svg width={width} height={HEIGHT} role="img" aria-label="Median year-on-year growth by quarter" className="block">
            {scale.ticks.map((tick) => (
              <g key={tick}>
                <line x1={PAD.left} x2={width - PAD.right} y1={y(tick)} y2={y(tick)} stroke="var(--border)" strokeWidth={tick === 0 ? 1.5 : 1} />
                <text x={PAD.left - 6} y={y(tick)} textAnchor="end" dominantBaseline="middle" className="tabular fill-muted-foreground text-[11px]">
                  {tick}
                </text>
              </g>
            ))}
            {columns.map((column, index) => {
              const left = PAD.left + group * index + (group - series.length * (bar + GAP) + GAP) / 2;
              return (
                <g key={column.label}>
                  {column.values.map((value, position) => {
                    const x = left + position * (bar + GAP);
                    const item = series[position];
                    if (value.median === null) {
                      return (
                        <text key={item.key} x={x + bar / 2} y={zero - 6} textAnchor="middle" className="fill-muted-foreground text-[11px]">
                          <title>{`${item.label}: no company had a growth rate`}</title>
                          –
                        </text>
                      );
                    }
                    const top = y(Math.max(value.median, 0));
                    const height = Math.max(1, Math.abs(y(value.median) - zero));
                    // Unsigned on the bar, where direction is the bar's; the table beneath keeps the sign.
                    const label = `${value.median.toFixed(1)}%`;
                    return (
                      <g key={item.key} tabIndex={0} className="outline-none focus-visible:[&>rect]:stroke-foreground">
                        <title>{`${item.label}: median ${label} across ${value.n} of ${column.results} results`}</title>
                        <rect x={x} y={top} width={bar} height={height} rx={2} fill={item.color} strokeWidth={2} stroke="transparent" />
                        <text
                          x={x + bar / 2}
                          y={value.median >= 0 ? top - 5 : top + height + 12}
                          textAnchor="middle"
                          className="tabular fill-foreground text-[11px] font-semibold"
                        >
                          {label}
                        </text>
                      </g>
                    );
                  })}
                  <text x={PAD.left + group * (index + 0.5)} y={HEIGHT - 24} textAnchor="middle" className="fill-foreground text-xs">
                    {column.label}
                  </text>
                  <text x={PAD.left + group * (index + 0.5)} y={HEIGHT - 9} textAnchor="middle" className="tabular fill-muted-foreground text-[11px]">
                    {`${column.results} ${column.results === 1 ? "result" : "results"}`}
                  </text>
                </g>
              );
            })}
            <text transform={`translate(10 ${PAD.top + plotHeight / 2}) rotate(-90)`} textAnchor="middle" className="fill-muted-foreground text-[11px]">
              Growth (%)
            </text>
          </svg>
        ) : (
          <div style={{ height: HEIGHT }} aria-hidden />
        )}
      </div>
    </figure>
  );
}
