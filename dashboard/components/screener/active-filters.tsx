"use client";

import { useCallback, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { X } from "lucide-react";

import { PendingMarker } from "@/components/nav-pending";
import { useMarket } from "@/components/market-provider";
import { CHOICES, LISTINGS } from "@/components/screener/filter-bar";
import { RANGES, readRanges, rangeLabel } from "@/lib/screener-ranges.mjs";
import { ELIGIBILITY_CLASSES } from "@/lib/types";

/**
 * One chip per active filter, each individually removable.
 *
 * The filter panel reports how many filters are on and offers to clear all of
 * them. Neither tells you *which* are on, so undoing one meant reopening the
 * panel and remembering what you had set -- and a shared link arrived with no
 * indication of what it was filtering at all. These chips are that missing
 * readout, and removing one is the same gesture as reading it.
 *
 * Multi-valued keys remove the single value on the chip rather than the whole
 * key, so dropping one of three sectors leaves the other two.
 */

const TOGGLE_LABELS: Record<string, string> = {
  actionable: "Executable only",
  buyEligible: "Passes BUY gates",
  excludeCapped: "Exclude capped",
  transcript: "Scoring-eligible transcript",
  redFlags: "Has red flags",
  aboveMa200: "Above 200-day average",
};

/** `keys` are every URL key the chip stands for: a range also answers to its old single-bound key. */
type Chip = { keys: string[]; value?: string; label: string };

function eligibilityLabel(value: string): string {
  const match = ELIGIBILITY_CLASSES.find(
    (item) => String(item.value) === value,
  );
  return match ? match.label : `Eligibility ${value}`;
}

export function ActiveFilters() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();
  const sizeSuffix = useMarket().code === "US" ? "M" : "Cr";

  const remove = useCallback(
    (keys: string[], value?: string) => {
      const params = new URLSearchParams(searchParams.toString());
      for (const key of keys) {
        const kept = value === undefined ? [] : params.getAll(key).filter((item) => item !== value);
        params.delete(key);
        kept.forEach((item) => params.append(key, item));
      }
      // Removing a filter widens the result set, so the old page offset is at
      // best wrong and at worst past the end of the new set.
      params.delete("page");
      startTransition(() => {
        const query = params.toString();
        router.push(query ? `${pathname}?${query}` : pathname, {
          scroll: false,
        });
      });
    },
    [pathname, router, searchParams],
  );

  const chips: Chip[] = [];

  const text = searchParams.get("q");
  if (text) chips.push({ keys: ["q"], label: `“${text}”` });

  for (const rating of searchParams.getAll("rating")) {
    chips.push({ keys: ["rating"], value: rating, label: rating });
  }
  for (const sector of searchParams.getAll("sector")) {
    chips.push({ keys: ["sector"], value: sector, label: sector });
  }
  for (const value of searchParams.getAll("eligibility")) {
    chips.push({
      keys: ["eligibility"],
      value,
      label: eligibilityLabel(value),
    });
  }
  for (const stage of searchParams.getAll("stage")) {
    chips.push({ keys: ["stage"], value: stage, label: stage });
  }
  for (const value of searchParams.getAll("listing")) {
    const option = LISTINGS.find((item) => item.value === value);
    if (option) chips.push({ keys: ["listing"], value, label: option.label });
  }
  for (const industry of searchParams.getAll("industry")) {
    chips.push({ keys: ["industry"], value: industry, label: industry });
  }
  for (const choice of CHOICES) {
    for (const value of searchParams.getAll(choice.key)) {
      const option = choice.options.find((item) => item.value === value);
      chips.push({ keys: [choice.key], value, label: `${choice.label}: ${option?.label ?? value}` });
    }
  }
  for (const [key, label] of Object.entries(TOGGLE_LABELS)) {
    if (searchParams.get(key) === "1") chips.push({ keys: [key], label });
  }
  const ranges = readRanges((key) => searchParams.get(key));
  for (const range of RANGES) {
    const value = ranges[range.key];
    if (value) {
      chips.push({
        keys: range.legacyMin ? [range.key, range.legacyMin] : [range.key],
        label: rangeLabel(range, value, sizeSuffix),
      });
    }
  }

  if (!chips.length) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label="Active filters">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        Filtering
      </span>
      <PendingMarker pending={pending} />
      {chips.map((chip) => (
        <span
          key={`${chip.keys[0]}:${chip.value ?? ""}`}
          className="inline-flex h-7 items-center gap-1 rounded-md border bg-muted pl-2.5 pr-1 text-[11px] font-medium"
        >
          {chip.label}
          <button
            type="button"
            onClick={() => remove(chip.keys, chip.value)}
            aria-label={`Remove filter ${chip.label}`}
            className="rounded-md p-0.5 text-muted-foreground transition-colors duration-(--duration-fast) hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="size-3" aria-hidden />
          </button>
        </span>
      ))}
    </div>
  );
}
