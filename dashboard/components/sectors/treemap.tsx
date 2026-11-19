"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { SegmentedControl } from "@/components/segmented-control";
import { squarify } from "@/lib/sectors.mjs";
import { cn } from "@/lib/utils";

/** One tile: what it is, where it goes, and every value a picker can size or colour it by. */
export type TreemapItem = {
  key: string;
  label: string;
  title: string;
  href: string;
  values: Record<string, number | null>;
};

/** A size option: a field of `values`, or `null` for equal weight. */
export type SizeOption = { value: string; label: string; field: string | null; format: (v: number | null) => string };

/**
 * A colour option. `diverging` is a change around zero, coloured
 * negative-neutral-positive and clipped at the chosen bound of `scales`;
 * `rank` is a level (ROE, P/E), coloured by its percentile among the tiles in
 * one hue, light to dark, because a level has no zero to diverge from.
 */
export type ColourOption = {
  value: string;
  label: string;
  field: string;
  kind: "diverging" | "rank";
  scales?: number[];
  format: (v: number | null) => string;
};

const MAX_TILES = 60;

/** Not reported: hatched, so it never reads as "no change". */
const MISSING = "repeating-linear-gradient(135deg, var(--control) 0 4px, var(--card) 4px 8px)";

function background(option: ColourOption, value: number | null, scale: number, rank: Map<number, number>) {
  if (value === null || !Number.isFinite(value)) return MISSING;
  if (option.kind === "diverging") {
    // Capped at 58% so the label in foreground ink stays readable on the tile.
    const share = Math.min(Math.abs(value) / scale, 1) * 58;
    const hue = value >= 0 ? "var(--positive)" : "var(--negative)";
    return `color-mix(in oklab, ${hue} ${share.toFixed(0)}%, var(--control))`;
  }
  const share = (rank.get(value) ?? 0) * 50 + 6;
  return `color-mix(in oklab, #6366f1 ${share.toFixed(0)}%, var(--control))`;
}

/**
 * Tiles sized by one measure and coloured by another, the largest
 * `MAX_TILES` drawn (every item is still in the list on the page). Pickers
 * above; below, a readout of the tile under the pointer or focus, so no value
 * hides in a tooltip.
 */
export function Treemap({
  items,
  sizes,
  colours,
  label,
  height = 420,
  note,
  highlight,
  controls = true,
}: {
  items: TreemapItem[];
  sizes: SizeOption[];
  colours: ColourOption[];
  label: string;
  height?: number;
  /** One line under the map: what area means and what it leaves out. */
  note?: string;
  /** The key of a tile to outline: the stock a reader came from. */
  highlight?: string;
  /** False draws the map alone, on its first size and colour, for a preview that links to the full page. */
  controls?: boolean;
}) {
  const [size, setSize] = useState(sizes[0].value);
  const [colour, setColour] = useState(colours[0].value);
  const colourOption = colours.find((option) => option.value === colour) ?? colours[0];
  const sizeOption = sizes.find((option) => option.value === size) ?? sizes[0];
  const [scale, setScale] = useState<number | null>(null);
  const scaleValue = scale ?? colourOption.scales?.[1] ?? colourOption.scales?.[0] ?? 3;
  const [active, setActive] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const node = box.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const mapHeight = width && width < 640 ? Math.round(height * 0.75) : height;
  const tiles = useMemo(() => {
    const sized = items
      .map((item) => ({ item, size: sizeOption.field ? (item.values[sizeOption.field] ?? 0) : 1 }))
      .filter((entry) => entry.size > 0)
      .sort((a, b) => b.size - a.size)
      .slice(0, MAX_TILES);
    return width ? squarify(sized, width, mapHeight) : [];
  }, [items, sizeOption.field, width, mapHeight]);

  const rank = useMemo(() => {
    const values = tiles
      .map((tile) => tile.item.values[colourOption.field])
      .filter((value): value is number => value !== null && Number.isFinite(value))
      .sort((a, b) => a - b);
    return new Map(values.map((value, index) => [value, values.length > 1 ? index / (values.length - 1) : 0.5]));
  }, [tiles, colourOption.field]);

  const shownItem = tiles.find((tile) => tile.item.key === active)?.item ?? null;
  const sizeText = (item: TreemapItem) =>
    sizeOption.field ? `${sizeOption.label} ${sizeOption.format(item.values[sizeOption.field] ?? null)}` : "";

  return (
    <div className="space-y-3">
      {controls ? <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <Picker label="Size">
          <SegmentedControl label="Size by" value={size} onChange={setSize} options={sizes} />
        </Picker>
        <Picker label="Colour">
          <SegmentedControl
            label="Colour by"
            value={colour}
            onChange={(value) => {
              setColour(value);
              setScale(null);
            }}
            options={colours}
          />
        </Picker>
        {colourOption.kind === "diverging" && colourOption.scales ? (
          <Picker label="Scale">
            <SegmentedControl
              label="Colour scale"
              value={String(scaleValue)}
              onChange={(value) => setScale(Number(value))}
              options={colourOption.scales.map((bound) => ({ value: String(bound), label: `±${bound}%` }))}
            />
          </Picker>
        ) : null}
      </div> : null}

      <div
        ref={box}
        role="list"
        aria-label={label}
        className="relative w-full overflow-hidden rounded-lg"
        style={{ height: mapHeight }}
        onMouseLeave={() => setActive(null)}
      >
        {tiles.map((tile) => {
          const value = tile.item.values[colourOption.field] ?? null;
          const roomy = tile.w > 54 && tile.h > 30;
          return (
            <div
              key={tile.item.key}
              role="listitem"
              className="absolute p-px"
              style={{ left: tile.x, top: tile.y, width: tile.w, height: tile.h }}
            >
              <Link
                prefetch={false}
                href={tile.item.href}
                aria-label={`${tile.item.title}: ${colourOption.label} ${colourOption.format(value)}${sizeText(tile.item) ? `, ${sizeText(tile.item)}` : ""}`}
                onMouseEnter={() => setActive(tile.item.key)}
                onFocus={() => setActive(tile.item.key)}
                onBlur={() => setActive(null)}
                aria-current={tile.item.key === highlight ? "true" : undefined}
                className={cn(
                  "flex h-full w-full flex-col items-center justify-center overflow-hidden rounded-[4px] text-center text-foreground transition-[filter] duration-(--duration-fast) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
                  active && active !== tile.item.key && "brightness-[0.94] dark:brightness-75",
                  tile.item.key === highlight && "ring-2 ring-foreground ring-inset",
                )}
                style={{ background: background(colourOption, value, scaleValue, rank) }}
              >
                {roomy ? (
                  <>
                    <span className="max-w-full truncate px-1 font-mono text-[11px] font-semibold leading-tight">
                      {tile.item.label}
                    </span>
                    {tile.h > 46 ? (
                      <span className="tabular font-mono text-[11px] leading-tight opacity-80">
                        {colourOption.format(value)}
                      </span>
                    ) : null}
                  </>
                ) : null}
              </Link>
            </div>
          );
        })}
      </div>

      <div className="flex min-h-5 flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span aria-live="polite">
          {shownItem ? (
            <>
              <span className="font-medium text-foreground">{shownItem.title}</span>
              {` · ${colourOption.label} ${colourOption.format(shownItem.values[colourOption.field] ?? null)}`}
              {sizeText(shownItem) ? ` · ${sizeText(shownItem)}` : ""}
            </>
          ) : colourOption.kind === "diverging" ? (
            `−${scaleValue}% to +${scaleValue}% · hatched: not reported`
          ) : (
            `${colourOption.label}: low to high · hatched: not reported`
          )}
        </span>
        <span>
          {tiles.length < items.length ? `Largest ${tiles.length} of ${items.length}` : null}
          {tiles.length < items.length && note ? " · " : null}
          {note}
        </span>
      </div>
    </div>
  );
}

function Picker({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="shrink-0 text-xs text-muted-foreground">{label}</span>
      <div className="max-w-full min-w-0 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {children}
      </div>
    </div>
  );
}
