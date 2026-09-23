"use client";

import { useDeferredValue, useMemo, useState } from "react";
import { Search, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { NewListingsList } from "@/components/new-listing";
import { STATUS_LABEL } from "@/lib/new-listings.mjs";
import type { Market } from "@/lib/markets";
import type { NewListingRow, NewListingStatus } from "@/lib/queries";

const STATUS_ORDER: NewListingStatus[] = [
  "insufficient_history",
  "below_liquidity_floor",
  "pending_run",
  "no_price_data",
];

/**
 * Search and status filter for the New listings page.
 *
 * Entirely in the browser. The page already holds every listing (a few hundred
 * rows), so filtering is a local pass on each keystroke -- no debounce, no
 * round trip -- which is the same instant response ⌘K gives. The match is the
 * screener grid's: a case-insensitive substring of symbol or company.
 */
export function NewListingsBrowser({
  rows,
  market,
}: {
  rows: NewListingRow[];
  market: Market;
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<NewListingStatus | "all">("all");
  // A few hundred rows re-render cheaply, but deferring keeps the keystroke
  // itself on the fast path if the list grows.
  const term = useDeferredValue(query.trim().toLowerCase());

  const counts = useMemo(() => {
    const out: Partial<Record<NewListingStatus, number>> = {};
    for (const row of rows) out[row.status] = (out[row.status] ?? 0) + 1;
    return out;
  }, [rows]);

  const visible = useMemo(
    () =>
      rows.filter(
        (row) =>
          (status === "all" || row.status === status) &&
          (!term || `${row.symbol} ${row.company ?? ""}`.toLowerCase().includes(term)),
      ),
    [rows, status, term],
  );

  const chips: { key: NewListingStatus | "all"; label: string; count: number }[] = [
    { key: "all", label: "All", count: rows.length },
    ...STATUS_ORDER.filter((key) => counts[key]).map((key) => ({
      key,
      label: STATUS_LABEL[key],
      count: counts[key] ?? 0,
    })),
  ];

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
        <div className="relative min-w-0 flex-1 sm:max-w-sm">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search symbol or company…"
            aria-label="Search new listings by symbol or company"
            className="h-9 pl-8"
          />
        </div>
        <div
          role="group"
          aria-label="Filter by status"
          className="flex max-w-full gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {chips.map((chip) => {
            const active = status === chip.key;
            return (
              <button
                key={chip.key}
                type="button"
                aria-pressed={active}
                onPointerDown={(event) => {
                  if (event.button === 0) setStatus(chip.key);
                }}
                onClick={() => setStatus(chip.key)}
                className={cn(
                  "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full px-3.5 text-xs font-medium whitespace-nowrap",
                  "transition-[background-color,color,transform] duration-(--duration-spring-bouncy) ease-(--ease-spring)",
                  "active:scale-[0.95] active:duration-(--duration-press) active:ease-out",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "bg-(--control) text-muted-foreground hover:bg-(--control-hover) hover:text-foreground",
                )}
              >
                {chip.label}
                <span className={cn("tabular", active ? "opacity-70" : "opacity-60")}>
                  {chip.count}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {visible.length ? (
        <NewListingsList rows={visible} market={market} />
      ) : (
        <div className="px-5 py-10 text-center">
          <p className="text-sm font-medium">No new listing matches “{query.trim()}”.</p>
          <button
            type="button"
            onClick={() => {
              setQuery("");
              setStatus("all");
            }}
            className="mt-2 inline-flex items-center gap-1 rounded-full text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="size-3" aria-hidden />
            Clear search
          </button>
        </div>
      )}
    </>
  );
}
