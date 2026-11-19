"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "next-themes";
import { LineSeries, LineStyle, createChart, type IChartApi, type UTCTimestamp } from "lightweight-charts";
import { Check, Loader2, Search, X } from "lucide-react";

import { formatPercent } from "@/lib/format";
import type { Market } from "@/lib/markets";
import { decodeSeries } from "@/lib/price-series.mjs";
import { rebase } from "@/lib/sectors.mjs";
import { useLiveQuotes } from "@/lib/use-live-quotes";
import { cn } from "@/lib/utils";

/** A constituent the reader can lay over the index. `d1` is the run's 1D change, percent. */
export type CompareMember = { symbol: string; company: string | null; d1?: number | null };

type Point = { time: string; value: number };

/** At most this many members at once: the categorical palette's slots 2-6. */
export const MAX_COMPARE = 5;

/**
 * Series colours. Canvas cannot read CSS variables, so these are hex. The
 * index keeps the stock chart's indigo; members take categorical slots 2-6 in
 * order (orange, aqua, yellow, magenta, green), each stepped for the dark
 * surface, validated as one palette for CVD separation and contrast in both
 * modes (dataviz validate_palette, 19 Nov 2026). A colour follows the member
 * for as long as it stays selected.
 */
const COLORS = {
  light: { index: "#4f46e5", members: ["#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"] },
  dark: { index: "#7478ef", members: ["#d95926", "#199e70", "#c98500", "#d55181", "#0ca30c"] },
};

/**
 * The browser's copy of the trading calendar and each series it has asked
 * for, read through /api/price-series (R2 only) once per page view.
 */
const calendars = new Map<string, Promise<string[] | null>>();
const series = new Map<string, Promise<Point[] | null>>();

async function getJson<T>(market: string, symbol: string): Promise<T | null> {
  const response = await fetch(`/api/price-series?market=${market}&symbol=${encodeURIComponent(symbol)}`);
  return response.ok ? ((await response.json()) as T) : null;
}

function calendar(market: string) {
  if (!calendars.has(market)) {
    const loaded = getJson<{ sessions?: string }>(market, "calendar")
      .then((body) => (body?.sessions ? (JSON.parse(body.sessions) as string[]) : null))
      .catch(() => null);
    loaded.then((sessions) => sessions ?? calendars.delete(market));
    calendars.set(market, loaded);
  }
  return calendars.get(market)!;
}

function memberSeries(market: string, symbol: string) {
  const key = `${market}:${symbol}`;
  if (!series.has(key)) {
    const loaded = Promise.all([calendar(market), getJson<Parameters<typeof decodeSeries>[0]>(market, symbol)])
      .then(([sessions, row]) =>
        sessions && row ? decodeSeries(row, sessions).points.map((p) => ({ time: p.time, value: p.close })) : null,
      )
      .catch(() => null);
    // A failed read is not kept, so a second click tries again.
    loaded.then((points) => points ?? series.delete(key));
    series.set(key, loaded);
  }
  return series.get(key)!;
}

/**
 * Which members are laid over the index, their series as they load, and
 * which failed. The colour slot is fixed when a member is picked.
 */
export function useCompare(market: Market) {
  const [picked, setPicked] = useState<{ symbol: string; slot: number }[]>([]);
  const [loaded, setLoaded] = useState<Record<string, Point[] | null>>({});

  const toggle = (symbol: string) => {
    const on = picked.some((entry) => entry.symbol === symbol);
    if (on) {
      setPicked(picked.filter((entry) => entry.symbol !== symbol));
      return;
    }
    if (picked.length >= MAX_COMPARE) return;
    const used = new Set(picked.map((entry) => entry.slot));
    const slot = [0, 1, 2, 3, 4].find((index) => !used.has(index)) ?? 0;
    setPicked([...picked, { symbol, slot }]);
    if (!loaded[symbol]) {
      setLoaded((current) => {
        const next = { ...current };
        delete next[symbol];
        return next;
      });
      memberSeries(market.code, symbol).then((points) => setLoaded((current) => ({ ...current, [symbol]: points })));
    }
  };

  return { picked, loaded, toggle, clear: () => setPicked([]) };
}

/**
 * The index and the picked members on one axis: percent change from the
 * first session of the range, TradingView's compare scale, so a ₹3,000 stock
 * and a level of 24,000 read side by side. Closes only; no candles.
 */
export function CompareLines({
  name,
  index,
  members,
  from,
  height = 320,
}: {
  name: string;
  index: Point[];
  members: { symbol: string; slot: number; points: Point[] }[];
  from: string;
  height?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const { resolvedTheme } = useTheme();
  const [hover, setHover] = useState<{ time: string; values: Map<string, number> } | null>(null);
  const dark = resolvedTheme === "dark";

  const lines = useMemo(() => {
    const colors = dark ? COLORS.dark : COLORS.light;
    return [
      { key: `index:${name}`, label: name, color: colors.index, points: rebase(index, from) as Point[] },
      ...members.map((member) => ({
        key: member.symbol,
        label: member.symbol,
        color: colors.members[member.slot],
        points: rebase(member.points, from) as Point[],
      })),
    ];
  }, [name, index, members, from, dark]);

  useEffect(() => {
    const node = container.current;
    if (!node || !resolvedTheme) return;
    const instance: IChartApi = createChart(node, {
      autoSize: true,
      height,
      layout: { background: { color: "transparent" }, textColor: dark ? "#8b95a8" : "#64748b", attributionLogo: false },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: dark ? "rgba(148,163,184,0.10)" : "rgba(100,116,139,0.14)" },
      },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { mode: 1 },
      localization: { priceFormatter: (value: number) => formatPercent(value, 1, true) },
      handleScroll: false,
      handleScale: false,
    });
    const drawn = new Map<unknown, string>();
    lines.forEach((line, position) => {
      const added = instance.addSeries(LineSeries, {
        color: line.color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerRadius: 4,
      });
      added.setData(line.points.map((point) => ({ time: point.time as unknown as UTCTimestamp, value: point.value })));
      if (position === 0) {
        added.createPriceLine({
          price: 0,
          color: dark ? "rgba(148,163,184,0.45)" : "rgba(100,116,139,0.5)",
          lineStyle: LineStyle.Dashed,
          lineWidth: 1,
          axisLabelVisible: false,
        });
      }
      drawn.set(added, line.key);
    });
    instance.timeScale().fitContent();
    instance.subscribeCrosshairMove((param) => {
      if (!param.time || !param.seriesData.size) {
        setHover(null);
        return;
      }
      const values = new Map<string, number>();
      for (const [api, datum] of param.seriesData) {
        const key = drawn.get(api);
        if (key && datum && "value" in datum) values.set(key, datum.value as number);
      }
      setHover({ time: String(param.time), values });
    });
    return () => instance.remove();
  }, [lines, dark, height, resolvedTheme]);

  return (
    <div className="space-y-2">
      <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs" aria-label="Series">
        {lines.map((line) => {
          const value = hover ? hover.values.get(line.key) : line.points.at(-1)?.value;
          return (
            <li key={line.key} className="inline-flex items-center gap-1.5">
              <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ backgroundColor: line.color }} />
              <span className="font-medium text-foreground">{line.label}</span>
              <span className="tabular font-mono text-muted-foreground">{formatPercent(value ?? null, 1, true)}</span>
            </li>
          );
        })}
        <li className="ml-auto text-muted-foreground">{hover ? hover.time : `Change since ${from}`}</li>
      </ul>
      <div
        ref={container}
        style={{ height }}
        className="w-full"
        role="img"
        aria-label={`${lines.map((line) => line.label).join(", ")}: percent change since ${from}`}
      />
    </div>
  );
}

/**
 * The members the reader can lay over the index, searchable, with each
 * one's 1D change (live during the session, else the run's).
 */
export function CompareList({
  market,
  members,
  picked,
  loaded,
  onToggle,
  onClear,
}: {
  market: Market;
  members: CompareMember[];
  picked: { symbol: string; slot: number }[];
  loaded: Record<string, Point[] | null>;
  onToggle: (symbol: string) => void;
  onClear: () => void;
}) {
  const [query, setQuery] = useState("");
  const { resolvedTheme } = useTheme();
  const colors = resolvedTheme === "dark" ? COLORS.dark : COLORS.light;
  const symbols = useMemo(() => members.map((member) => member.symbol), [members]);
  const live = useLiveQuotes(market.code, symbols);
  const term = query.trim().toLowerCase();
  const shown = term
    ? members.filter(
        (member) => member.symbol.toLowerCase().includes(term) || (member.company ?? "").toLowerCase().includes(term),
      )
    : members;
  const slotOf = new Map(picked.map((entry) => [entry.symbol, entry.slot]));
  const full = picked.length >= MAX_COMPARE;

  return (
    <div className="panel flex h-full max-h-[26rem] min-h-0 flex-col overflow-hidden lg:max-h-[30rem]">
      <div className="space-y-2 border-b border-border p-3">
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="text-sm font-semibold">Compare members</h3>
          {picked.length ? (
            <button
              type="button"
              onClick={onClear}
              className="rounded text-xs font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Clear {picked.length}
            </button>
          ) : (
            <span className="text-xs text-muted-foreground">Up to {MAX_COMPARE}</span>
          )}
        </div>
        <label className="relative block">
          <span className="sr-only">Search members</span>
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
          />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search ticker or name"
            className="h-8 w-full rounded-md bg-(--control) pr-2 pl-8 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </label>
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto py-1" aria-label="Members">
        {shown.map((member) => {
          const slot = slotOf.get(member.symbol);
          const on = slot !== undefined;
          const loading = on && !(member.symbol in loaded);
          const failed = on && member.symbol in loaded && loaded[member.symbol] === null;
          const change = live(member.symbol)?.change_pct ?? member.d1 ?? null;
          return (
            <li key={member.symbol}>
              <button
                type="button"
                aria-pressed={on}
                disabled={!on && full}
                onClick={() => onToggle(member.symbol)}
                title={failed ? "No price history to draw" : full && !on ? `Up to ${MAX_COMPARE} at once` : undefined}
                className="flex w-full items-center gap-2.5 px-3 py-1.5 text-left transition-colors duration-(--duration-fast) hover:bg-(--control) focus-visible:bg-(--control) focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span
                  aria-hidden
                  className={cn(
                    "flex size-4 shrink-0 items-center justify-center rounded-[4px] ring-1 ring-border",
                    on && "ring-0",
                  )}
                  style={on ? { backgroundColor: colors.members[slot] } : undefined}
                >
                  {loading ? (
                    <Loader2 className="size-3 animate-spin text-white" />
                  ) : failed ? (
                    <X className="size-3 text-white" />
                  ) : on ? (
                    <Check className="size-3 text-white" />
                  ) : null}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-xs font-semibold">{member.symbol}</span>
                  {member.company ? (
                    <span className="block truncate text-[11px] text-muted-foreground">{member.company}</span>
                  ) : null}
                </span>
                <span
                  className={cn(
                    "tabular shrink-0 font-mono text-xs",
                    change === null ? "text-muted-foreground" : change >= 0 ? "text-positive" : "text-negative",
                  )}
                >
                  {formatPercent(change, 2, true)}
                </span>
              </button>
            </li>
          );
        })}
        {!shown.length ? (
          <li className="px-3 py-6 text-center text-xs text-muted-foreground">No member matches “{query}”</li>
        ) : null}
      </ul>
    </div>
  );
}
