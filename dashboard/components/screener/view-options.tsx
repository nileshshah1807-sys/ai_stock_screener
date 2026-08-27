"use client";

import { useCallback, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Columns3, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  HIDEABLE_COLUMNS,
  parseDensity,
  parseHiddenColumns,
  serializeHiddenColumns,
  type ColumnId,
  type Density,
} from "@/lib/columns";
import { cn } from "@/lib/utils";

const DENSITIES: ReadonlyArray<{ value: Density; label: string }> = [
  { value: "compact", label: "Compact" },
  { value: "comfortable", label: "Comfortable" },
];

/**
 * Column visibility and row density.
 *
 * Both live in the URL rather than in localStorage, which is a deliberate
 * departure from where a personal preference would normally go. The reason is
 * that hiding a column here also narrows the Supabase projection, so the choice
 * has to be known on the server before the rows are fetched -- and putting it in
 * the URL means it travels with a saved view, so "the four columns I care about"
 * is part of the screen you share rather than a setting the recipient has to
 * reproduce.
 *
 * The tradeoff is that a shared link imposes the sender's density on the
 * recipient. That is the smaller cost.
 */
export function ViewOptions({ factorModel = false }: { factorModel?: boolean }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();

  const hidden = new Set<ColumnId>(
    parseHiddenColumns(searchParams.get("cols") ?? undefined),
  );
  const density = parseDensity(searchParams.get("density") ?? undefined);

  // A run is one model or the other for its whole cross-section, so offering
  // the columns that did not run would list toggles with nothing behind them.
  const columns = HIDEABLE_COLUMNS.filter((column) => {
    const availability = column.availability ?? "always";
    if (availability === "factor") return factorModel;
    if (availability === "legacy") return !factorModel;
    return true;
  });

  const push = useCallback(
    (mutate: (params: URLSearchParams) => void) => {
      const params = new URLSearchParams(searchParams.toString());
      mutate(params);
      // Neither control changes which rows match, so the page offset survives.
      // Losing your place on page 6 because you hid a column would be its own
      // small bug.
      startTransition(() => {
        const query = params.toString();
        router.push(query ? `${pathname}?${query}` : pathname, {
          scroll: false,
        });
      });
    },
    [pathname, router, searchParams],
  );

  const toggleColumn = (id: ColumnId) => {
    const next = new Set(hidden);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    push((params) => {
      const value = serializeHiddenColumns(next);
      if (value) params.set("cols", value);
      else params.delete("cols");
    });
  };

  const setDensity = (value: Density) => {
    push((params) => {
      if (value === "comfortable") params.set("density", value);
      else params.delete("density");
    });
  };

  const reset = () =>
    push((params) => {
      params.delete("cols");
      params.delete("density");
    });

  const hiddenCount = [...hidden].filter((id) =>
    columns.some((column) => column.id === id),
  ).length;

  return (
    <Popover>
      <PopoverTrigger render={<Button variant="outline" className="gap-1.5" />}>
        <Columns3 className="size-3.5" aria-hidden />
        <span className="hidden sm:inline">Columns</span>
        {hiddenCount ? (
          <span className="tabular ml-0.5 rounded bg-primary px-1.5 text-[10px] font-semibold text-primary-foreground">
            {hiddenCount}
          </span>
        ) : null}
      </PopoverTrigger>

      <PopoverContent align="end" className="w-72">
        <div className="space-y-4">
          <fieldset>
            <legend className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Visible columns
            </legend>
            <div className="max-h-64 space-y-1.5 overflow-y-auto pr-1">
              {columns.map((column) => (
                <div key={column.id} className="flex items-center gap-2">
                  <Checkbox
                    id={`column-${column.id}`}
                    checked={!hidden.has(column.id)}
                    onCheckedChange={() => toggleColumn(column.id)}
                  />
                  <Label
                    htmlFor={`column-${column.id}`}
                    className="cursor-pointer text-sm font-normal"
                  >
                    {column.label}
                  </Label>
                </div>
              ))}
            </div>
            <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
              Rank, Stock and Score always show. Hiding a column also drops it
              from the query, so a narrower grid is a lighter one.
            </p>
          </fieldset>

          <fieldset>
            <legend className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Row density
            </legend>
            <div
              className="flex gap-1"
              role="group"
              aria-label="Row density"
            >
              {DENSITIES.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  aria-pressed={density === option.value}
                  onClick={() => setDensity(option.value)}
                  className={cn(
                    "inline-flex h-8 flex-1 items-center justify-center rounded-full border text-xs font-medium",
                    "transition-colors duration-(--duration-fast) ease-(--ease-standard)",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    density === option.value
                      ? "border-primary bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground hover:bg-accent hover:text-foreground",
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </fieldset>

          {hiddenCount || density !== "compact" ? (
            <Button variant="ghost" className="h-8 w-full gap-1.5 text-xs" onClick={reset}>
              <RotateCcw className="size-3" aria-hidden />
              Reset to defaults
            </Button>
          ) : null}
        </div>
      </PopoverContent>
    </Popover>
  );
}
