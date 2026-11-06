"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type gsapType from "gsap";
import type { Flip as FlipPlugin } from "gsap/Flip";

import { SAMPLE_MARKETS, sampleRows } from "@/lib/landing.mjs";
import { cn } from "@/lib/utils";

// gsap and Flip load after first paint (see the effect in HeroGrid); until then a change simply happens.
type Motion = { gsap: typeof gsapType; Flip: typeof FlipPlugin };

type MarketKey = keyof typeof SAMPLE_MARKETS;
type Row = { symbol: string; name: string; price: number; day: number; cap: number; pe: number | null; stage: number };

type SortKey = "price" | "day" | "cap" | "pe" | "stage";
type Sort = { key: SortKey; dir: "desc" | "asc" } | null;
const COLUMNS: { key: SortKey; label: string; hide?: boolean }[] = [
  { key: "price", label: "Price" },
  { key: "day", label: "1D" },
  { key: "cap", label: "Mkt cap", hide: true },
  { key: "pe", label: "P/E", hide: true },
  { key: "stage", label: "Stage" },
];

/** Descending, then ascending, then the sample's own order; a missing P/E sorts last either way. */
function sorted(rows: Row[], sort: Sort) {
  if (!sort) return rows;
  const sign = sort.dir === "desc" ? -1 : 1;
  return [...rows].sort((a, b) => {
    const x = a[sort.key];
    const y = b[sort.key];
    if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
    return (x - y) * sign;
  });
}

const chip =
  "inline-flex h-8 items-center rounded-md border px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/**
 * A working picture of the screener's grid: the market switch and the Stage 2
 * filter really filter the sample rows. The companies are invented and the
 * caption says so; nothing here is a quote. No rating column is drawn.
 */
export function HeroGrid() {
  const [market, setMarket] = useState<MarketKey>("ind");
  const [stage2, setStage2] = useState(false);
  const [sort, setSort] = useState<Sort>(null);
  const sample = SAMPLE_MARKETS[market];
  const rows = sorted(sampleRows(market, stage2), sort);
  const body = useRef<HTMLTableSectionElement>(null);
  // What the next layout effect should play: rows sliding to their new places
  // (sort, filter) or arriving fresh (market switch).
  const motion = useRef<Motion | null>(null);
  useEffect(() => {
    let live = true;
    Promise.all([import("gsap"), import("gsap/Flip")]).then(([g, f]) => {
      if (!live) return;
      g.default.registerPlugin(f.Flip);
      motion.current = { gsap: g.default, Flip: f.Flip };
    });
    return () => {
      live = false;
    };
  }, []);
  const pending = useRef<{ kind: "flip"; state: ReturnType<typeof FlipPlugin.getState> } | { kind: "arrive" } | null>(null);

  const change = (kind: "flip" | "arrive", update: () => void) => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!reduced && body.current && motion.current) {
      pending.current = kind === "flip" ? { kind, state: motion.current.Flip.getState(body.current.querySelectorAll("tr")) } : { kind };
    }
    update();
  };

  useLayoutEffect(() => {
    const todo = pending.current;
    pending.current = null;
    if (!todo || !body.current || !motion.current) return;
    const { gsap, Flip } = motion.current;
    const trs = body.current.querySelectorAll("tr");
    if (todo.kind === "flip") Flip.from(todo.state, { targets: trs, duration: 0.55, ease: "expo.out", onEnter: (els) => gsap.from(els, { opacity: 0, y: 10, duration: 0.4, ease: "expo.out" }) });
    else gsap.from(trs, { opacity: 0, y: 12, duration: 0.5, ease: "expo.out", stagger: 0.05, clearProps: "transform,opacity" });
  }, [market, stage2, sort]);

  const cycle = (key: SortKey) =>
    change("flip", () => setSort((cur) => (cur?.key !== key ? { key, dir: "desc" } : cur.dir === "desc" ? { key, dir: "asc" } : null)));

  return (
    <figure className="panel overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b p-3">
        <div role="group" aria-label="Sample market" className="flex gap-1 rounded-md bg-(--glass) p-0.5">
          {(Object.keys(SAMPLE_MARKETS) as MarketKey[]).map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={market === key}
              onClick={() => market !== key && change("arrive", () => setMarket(key))}
              className={cn(
                "h-8 rounded px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                market === key ? "bg-(--lens) text-foreground shadow-(--lens-shadow)" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {SAMPLE_MARKETS[key].label}
            </button>
          ))}
        </div>
        <button
          type="button"
          aria-pressed={stage2}
          onClick={() => change("flip", () => setStage2((v) => !v))}
          className={cn(chip, stage2 ? "border-brand bg-brand-soft text-brand" : "border-border text-muted-foreground hover:text-foreground")}
        >
          Stage 2 only
        </button>
        <span className="ml-auto text-xs text-muted-foreground tabular-nums" aria-live="polite">
          {rows.length} of {sample.rows.length} shown
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[22rem] text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th scope="col" className="px-3 py-2 font-medium">Stock</th>
              {COLUMNS.map((col) => {
                const active = sort?.key === col.key;
                return (
                  <th key={col.key} scope="col" aria-sort={active ? (sort.dir === "desc" ? "descending" : "ascending") : undefined} className={cn("px-1 py-1 text-right font-medium", col.hide && "hidden sm:table-cell")}>
                    <button
                      type="button"
                      onClick={() => cycle(col.key)}
                      className={cn("inline-flex h-8 items-center gap-1 rounded px-2 transition-colors hover:bg-(--control) hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", active && "text-foreground")}
                    >
                      {col.label}
                      <span aria-hidden className={cn("text-[10px] leading-none transition-opacity", active ? "text-brand opacity-100" : "opacity-0")}>{sort?.dir === "asc" ? "▲" : "▼"}</span>
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody ref={body} className="tabular-nums">
            {rows.map((row: Row) => (
              <tr key={`${market}-${row.symbol}`} className="border-b bg-card transition-colors last:border-0 hover:bg-(--control)">
                <td className="px-3 py-2.5">
                  <span className="font-semibold">{row.symbol}</span>
                  <span className="block max-w-[9rem] truncate text-xs text-muted-foreground">{row.name}</span>
                </td>
                <td className="px-3 py-2.5 text-right">{sample.money(row.price)}</td>
                <td className={cn("px-3 py-2.5 text-right", row.day >= 0 ? "text-positive" : "text-negative")}>
                  {row.day >= 0 ? "+" : "−"}
                  {Math.abs(row.day).toFixed(2)}%
                </td>
                <td className="hidden px-3 py-2.5 text-right sm:table-cell">{sample.cap(row.cap)}</td>
                <td className="hidden px-3 py-2.5 text-right sm:table-cell">{row.pe === null ? "—" : row.pe.toFixed(1)}</td>
                <td className="px-3 py-2.5 text-right">
                  <span className={cn("rounded px-1.5 py-0.5 text-xs font-medium", row.stage === 2 ? "bg-brand-soft text-brand" : "bg-(--control) text-muted-foreground")}>
                    {row.stage}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <figcaption className="border-t px-3 py-2 text-xs text-muted-foreground">
        Sample layout with invented companies, not live data. Try the market switch and the filter.
      </figcaption>
    </figure>
  );
}
