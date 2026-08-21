"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "next-themes";
import {
  AreaSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";

import {
  RANGES,
  clipFrom,
  decodeSeries,
  movingAverage,
  sliceRange,
} from "@/lib/price-series.mjs";

/**
 * Daily price, volume and the 50/200-day averages for one symbol.
 *
 * Drawn from this project's own archive rather than an embed. TradingView's
 * free widget does not serve NSE equities, and even where a third-party feed is
 * available it is the wrong source here: the chart has to agree with the prices
 * the model scored on, which are corporate-action adjusted by
 * `backtest/corporate_actions.py`. A chart that disagrees with the screener
 * beside it is worse than no chart.
 *
 * The averages are computed over the whole series and then clipped to the
 * visible range, so a 1M view still shows a true 200-day average rather than
 * one restarted at the left edge of the window.
 */

/**
 * The encoded row, decoded in the browser rather than on the server.
 *
 * Decoding server-side would put ~2,100 expanded objects into the RSC payload,
 * roughly triple the ~22 KB the three encoded arrays cost. The decoder is a few
 * hundred bytes, so shipping it and the compact form is the cheaper trade.
 */
export type EncodedSeries = {
  session_deltas: string;
  closes: string;
  volumes: string;
};

/**
 * Volume occupies the lower quarter of the pane.
 *
 * A separate pane would halve the space given to price, and price is what the
 * reader came for; scaling volume into its own margin keeps both legible
 * without splitting the frame.
 */
const VOLUME_SCALE_MARGIN = { top: 0.78, bottom: 0 };
const PRICE_SCALE_MARGIN = { top: 0.08, bottom: 0.26 };

const MA50_COLOR = "#f59e0b";

function palette(dark: boolean) {
  return {
    text: dark ? "#8b95a8" : "#64748b",
    grid: dark ? "rgba(148,163,184,0.10)" : "rgba(100,116,139,0.14)",
    price: dark ? "#818cf8" : "#4f46e5",
    priceFillTop: dark ? "rgba(129,140,248,0.28)" : "rgba(79,70,229,0.22)",
    priceFillBottom: dark ? "rgba(129,140,248,0.02)" : "rgba(79,70,229,0.02)",
    ma50: MA50_COLOR,
    ma200: dark ? "#94a3b8" : "#64748b",
    volume: dark ? "rgba(129,140,248,0.42)" : "rgba(79,70,229,0.30)",
  };
}

export function PriceChart({
  series,
  sessions,
  height = 380,
}: {
  series: EncodedSeries | null;
  sessions: string[];
  height?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const { resolvedTheme } = useTheme();
  const [rangeLabel, setRangeLabel] = useState("1Y");

  const decoded = useMemo(
    () => decodeSeries(series, sessions),
    [series, sessions],
  );
  const points = decoded.points;

  const range = RANGES.find((entry) => entry.label === rangeLabel) ?? RANGES[2];

  // Averages come from the full series; only the view is sliced.
  const { visible, ma50, ma200 } = useMemo(() => {
    const full50 = movingAverage(points, 50);
    const full200 = movingAverage(points, 200);
    const slice = sliceRange(points, range.sessions);
    const from = slice[0]?.time;
    return {
      visible: slice,
      ma50: clipFrom(full50, from),
      ma200: clipFrom(full200, from),
    };
  }, [points, range.sessions]);

  useEffect(() => {
    if (!resolvedTheme) return;
    const node = container.current;
    if (!node || visible.length === 0) return;

    const colors = palette(resolvedTheme === "dark");
    const instance: IChartApi = createChart(node, {
      height,
      layout: {
        background: { color: "transparent" },
        textColor: colors.text,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: colors.grid },
        horzLines: { color: colors.grid },
      },
      rightPriceScale: { borderVisible: false, scaleMargins: PRICE_SCALE_MARGIN },
      timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { mode: 1 },
      handleScroll: false,
      handleScale: false,
    });

    // Volume first, so the price line draws over it.
    const volume = instance.addSeries(HistogramSeries, {
      color: colors.volume,
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    instance
      .priceScale("volume")
      .applyOptions({ scaleMargins: VOLUME_SCALE_MARGIN });
    volume.setData(
      visible.map((point) => ({
        time: point.time as unknown as UTCTimestamp,
        value: point.volume,
      })),
    );

    const price = instance.addSeries(AreaSeries, {
      lineColor: colors.price,
      topColor: colors.priceFillTop,
      bottomColor: colors.priceFillBottom,
      lineWidth: 2,
      priceLineVisible: false,
    });
    price.setData(
      visible.map((point) => ({
        time: point.time as unknown as UTCTimestamp,
        value: point.close,
      })),
    );

    // Only draw an average that has a full window behind it.
    const averages = [
      { data: ma50, color: colors.ma50, title: "50 DMA" },
      { data: ma200, color: colors.ma200, title: "200 DMA" },
    ];
    for (const average of averages) {
      if (average.data.length === 0) continue;
      const line = instance.addSeries(LineSeries, {
        color: average.color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        title: average.title,
      });
      line.setData(
        average.data.map((point) => ({
          time: point.time as unknown as UTCTimestamp,
          value: point.value,
        })),
      );
    }

    instance.timeScale().fitContent();

    const observer = new ResizeObserver(([entry]) => {
      instance.applyOptions({ width: entry.contentRect.width });
    });
    observer.observe(node);

    return () => {
      observer.disconnect();
      instance.remove();
    };
  }, [visible, ma50, ma200, resolvedTheme, height]);

  if (points.length === 0) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        {decoded.ok
          ? "No price history published for this symbol yet."
          : "This symbol's price series could not be read. The scores on this page are unaffected."}
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1">
        {RANGES.map((entry) => {
          // A range longer than the series renders an identical chart under a
          // different label, which reads as a bug. Max always stays.
          const reachable =
            entry.sessions === null || entry.sessions < points.length;
          if (!reachable) return null;
          const active = entry.label === rangeLabel;
          return (
            <button
              key={entry.label}
              type="button"
              onClick={() => setRangeLabel(entry.label)}
              aria-pressed={active}
              className={`rounded-row px-2.5 py-1 text-xs font-medium transition-colors ${
                active
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-muted/40"
              }`}
            >
              {entry.label}
            </button>
          );
        })}
        <span className="ml-auto flex items-center gap-3 text-[11px] text-muted-foreground">
          <Swatch color={MA50_COLOR} label="50 DMA" />
          <Swatch color="#94a3b8" label="200 DMA" />
        </span>
      </div>

      <div ref={container} style={{ height }} />

      <p className="text-xs leading-relaxed text-muted-foreground">
        Adjusted closes from this project&rsquo;s own NSE bhavcopy archive &mdash;
        the same series the model is scored on. Splits and bonus issues are
        already applied, so the line is continuous across them. Sessions a stock
        did not trade are left as gaps rather than filled.
      </p>
    </div>
  );
}

function Swatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        aria-hidden
        className="inline-block h-0.5 w-3.5 rounded-full"
        style={{ background: color }}
      />
      {label}
    </span>
  );
}
