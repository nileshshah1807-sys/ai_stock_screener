"use client";

import { useCallback, useEffect, useMemo, useState, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Loader2, Search, SlidersHorizontal, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ELIGIBILITY_CLASSES, RATINGS } from "@/lib/types";
import { cn } from "@/lib/utils";

const TOGGLES = [
  {
    key: "actionable",
    label: "Executable only",
    hint: "Portfolio_Actionable: the target position can realistically be built at the configured participation rate.",
  },
  {
    key: "buyEligible",
    label: "Passes BUY gates",
    hint: "Coverage, trend, and data-quality gates all satisfied.",
  },
  {
    key: "excludeCapped",
    label: "Exclude capped",
    hint: "Hide rows whose rating is held below their score by a policy ceiling.",
  },
  {
    key: "transcript",
    label: "Scoring-eligible transcript",
    hint: "A current-cycle call that actually carries weight, not merely one on file.",
  },
  {
    key: "redFlags",
    label: "Has red flags",
    hint: "Shadow evidence only; never affects the live score or rating.",
  },
] as const;

/**
 * Model 5.0 only. Hidden entirely on a 4.x run, because these columns are null
 * there and PostgREST comparisons exclude nulls -- offering the control would
 * silently empty the grid rather than do nothing.
 */
const FACTOR_TOGGLES = [
  {
    key: "aboveMa200",
    label: "Above 200-day average",
    hint: "Price at or above its 200-day average. The BUY gate itself allows a 2% tolerance band below it.",
  },
] as const;

export function FilterBar({
  sectors,
  factorModel = false,
}: {
  sectors: string[];
  factorModel?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();

  const [query, setQuery] = useState(searchParams.get("q") ?? "");

  const activeRatings = useMemo(
    () => searchParams.getAll("rating"),
    [searchParams],
  );
  const activeSectors = useMemo(
    () => searchParams.getAll("sector"),
    [searchParams],
  );

  const push = useCallback(
    (mutate: (params: URLSearchParams) => void) => {
      const params = new URLSearchParams(searchParams.toString());
      mutate(params);
      // Any filter change invalidates the current page offset; staying on
      // page 7 of a now-3-page result set would render an empty grid.
      params.delete("page");
      startTransition(() => {
        router.push(`${pathname}?${params.toString()}`, { scroll: false });
      });
    },
    [pathname, router, searchParams],
  );

  // Debounced text filter: one request per pause, not per keystroke.
  useEffect(() => {
    const current = searchParams.get("q") ?? "";
    if (query === current) return;

    const timer = setTimeout(() => {
      push((params) => {
        if (query.trim()) params.set("q", query.trim());
        else params.delete("q");
      });
    }, 300);

    return () => clearTimeout(timer);
  }, [query, push, searchParams]);

  const toggleValue = (key: string, value: string) => {
    push((params) => {
      const existing = params.getAll(key);
      params.delete(key);
      const next = existing.includes(value)
        ? existing.filter((item) => item !== value)
        : [...existing, value];
      next.forEach((item) => params.append(key, item));
    });
  };

  const toggleFlag = (key: string) => {
    push((params) => {
      if (params.get(key) === "1") params.delete(key);
      else params.set(key, "1");
    });
  };

  const activeFilterCount =
    activeRatings.length +
    activeSectors.length +
    TOGGLES.filter((toggle) => searchParams.get(toggle.key) === "1").length +
    (searchParams.get("minScore") ? 1 : 0) +
    // Factor filters are only reachable when the run used the factor model,
    // but count them unconditionally so a shared URL carrying one still shows
    // an accurate badge.
    FACTOR_TOGGLES.filter((toggle) => searchParams.get(toggle.key) === "1")
      .length +
    searchParams.getAll("eligibility").length +
    (searchParams.get("minQuality") ? 1 : 0) +
    (searchParams.get("minMomentum") ? 1 : 0);

  const clearAll = () => {
    setQuery("");
    startTransition(() => router.push(pathname, { scroll: false }));
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-56 flex-1">
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter by symbol or company…"
          aria-label="Filter by symbol or company"
          className="h-9 pl-8"
        />
        {pending ? (
          <Loader2
            className="absolute right-2.5 top-1/2 size-3.5 -translate-y-1/2 animate-spin text-muted-foreground"
            aria-hidden
          />
        ) : null}
      </div>

      {/* Rating is the highest-traffic filter, so it stays visible rather than
          hiding behind the popover. */}
      <div
        className="flex flex-wrap items-center gap-1"
        role="group"
        aria-label="Filter by rating"
      >
        {RATINGS.map((rating) => {
          const active = activeRatings.includes(rating);
          return (
            <button
              key={rating}
              type="button"
              onClick={() => toggleValue("rating", rating)}
              aria-pressed={active}
              // h-9 and rounded-full so these sit on the same baseline and
              // share the same silhouette as every other control in the row.
              // Previously they had no height at all and a rounded-md corner,
              // which left them visibly shorter and squarer than the search
              // field and buttons either side of them.
              className={cn(
                "inline-flex h-9 items-center rounded-full border px-3.5 text-[11px] font-semibold uppercase tracking-wide",
                "transition-colors duration-(--duration-fast) ease-(--ease-standard)",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                active
                  ? "border-primary bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-accent hover:text-foreground",
              )}
            >
              {rating}
            </button>
          );
        })}
      </div>

      <Popover>
        <PopoverTrigger
          render={<Button variant="outline" className="gap-1.5" />}
        >
          <SlidersHorizontal className="size-3.5" aria-hidden />
          Filters
          {activeFilterCount ? (
            <span className="tabular ml-0.5 rounded bg-primary px-1.5 text-[10px] font-semibold text-primary-foreground">
              {activeFilterCount}
            </span>
          ) : null}
        </PopoverTrigger>

        <PopoverContent align="end" className="w-80">
          <div className="space-y-4">
            <fieldset className="space-y-2">
              <legend className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Evidence and execution
              </legend>
              {TOGGLES.map((toggle) => (
                <div key={toggle.key} className="flex items-start gap-2">
                  <Checkbox
                    id={toggle.key}
                    checked={searchParams.get(toggle.key) === "1"}
                    onCheckedChange={() => toggleFlag(toggle.key)}
                    className="mt-0.5"
                  />
                  <div className="min-w-0">
                    <Label
                      htmlFor={toggle.key}
                      className="cursor-pointer text-sm font-normal"
                    >
                      {toggle.label}
                    </Label>
                    <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
                      {toggle.hint}
                    </p>
                  </div>
                </div>
              ))}
            </fieldset>

            <fieldset className="space-y-1.5">
              <legend className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Minimum decision score
              </legend>
              <Input
                type="number"
                min={0}
                max={100}
                step={1}
                inputMode="numeric"
                defaultValue={searchParams.get("minScore") ?? ""}
                placeholder="e.g. 60"
                aria-label="Minimum decision score"
                className="tabular h-9"
                onBlur={(event) => {
                  const value = event.target.value.trim();
                  push((params) => {
                    if (value) params.set("minScore", value);
                    else params.delete("minScore");
                  });
                }}
              />
            </fieldset>

            {factorModel ? (
              <>
                <fieldset className="space-y-1.5">
                  <legend className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Factor percentiles
                  </legend>
                  <div className="grid grid-cols-2 gap-2">
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      inputMode="numeric"
                      defaultValue={searchParams.get("minQuality") ?? ""}
                      placeholder="Quality ≥"
                      aria-label="Minimum quality percentile"
                      className="tabular h-9"
                      onBlur={(event) => {
                        const value = event.target.value.trim();
                        push((params) => {
                          if (value) params.set("minQuality", value);
                          else params.delete("minQuality");
                        });
                      }}
                    />
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      inputMode="numeric"
                      defaultValue={searchParams.get("minMomentum") ?? ""}
                      placeholder="Momentum ≥"
                      aria-label="Minimum momentum percentile"
                      className="tabular h-9"
                      onBlur={(event) => {
                        const value = event.target.value.trim();
                        push((params) => {
                          if (value) params.set("minMomentum", value);
                          else params.delete("minMomentum");
                        });
                      }}
                    />
                  </div>
                  <p className="text-[11px] leading-snug text-muted-foreground">
                    Rank within the cross-section. BUY needs quality 40; STRONG
                    BUY needs quality 70, growth 60 and momentum 70.
                  </p>
                </fieldset>

                <fieldset className="space-y-1.5">
                  <legend className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Eligibility
                  </legend>
                  {ELIGIBILITY_CLASSES.map((item) => (
                    <div key={item.value} className="flex items-start gap-2">
                      <Checkbox
                        id={`eligibility-${item.value}`}
                        checked={searchParams
                          .getAll("eligibility")
                          .includes(String(item.value))}
                        onCheckedChange={() =>
                          toggleValue("eligibility", String(item.value))
                        }
                      />
                      <Label
                        htmlFor={`eligibility-${item.value}`}
                        className="cursor-pointer text-xs font-normal leading-snug"
                      >
                        {item.label}
                      </Label>
                    </div>
                  ))}
                </fieldset>

                <fieldset className="space-y-1.5">
                  {FACTOR_TOGGLES.map((toggle) => (
                    <div key={toggle.key} className="flex items-start gap-2">
                      <Checkbox
                        id={toggle.key}
                        checked={searchParams.get(toggle.key) === "1"}
                        onCheckedChange={() => toggleFlag(toggle.key)}
                      />
                      <div className="space-y-0.5">
                        <Label
                          htmlFor={toggle.key}
                          className="cursor-pointer text-xs font-normal leading-snug"
                        >
                          {toggle.label}
                        </Label>
                        <p className="text-[11px] leading-snug text-muted-foreground">
                          {toggle.hint}
                        </p>
                      </div>
                    </div>
                  ))}
                </fieldset>
              </>
            ) : null}

            {sectors.length ? (
              <fieldset>
                <legend className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Sector
                </legend>
                <div className="max-h-48 space-y-1.5 overflow-y-auto pr-1">
                  {sectors.map((sector) => (
                    <div key={sector} className="flex items-center gap-2">
                      <Checkbox
                        id={`sector-${sector}`}
                        checked={activeSectors.includes(sector)}
                        onCheckedChange={() => toggleValue("sector", sector)}
                      />
                      <Label
                        htmlFor={`sector-${sector}`}
                        className="cursor-pointer text-sm font-normal"
                      >
                        {sector}
                      </Label>
                    </div>
                  ))}
                </div>
              </fieldset>
            ) : null}
          </div>
        </PopoverContent>
      </Popover>

      {activeFilterCount || query ? (
        <Button variant="ghost" className="gap-1" onClick={clearAll}>
          <X className="size-3.5" aria-hidden />
          Clear
        </Button>
      ) : null}
    </div>
  );
}
