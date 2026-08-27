"use client";

import { useCallback, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { X } from "lucide-react";

import { ELIGIBILITY_CLASSES } from "@/lib/types";

/**
 * One chip per active filter, each individually removable.
 *
 * The filter popover reports how many filters are on and offers to clear all of
 * them. Neither tells you *which* are on, so undoing one meant reopening the
 * popover and remembering what you had set -- and a shared link arrived with no
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

const NUMERIC_LABELS: Record<string, (value: string) => string> = {
  minScore: (value) => `Score ≥ ${value}`,
  maxScore: (value) => `Score ≤ ${value}`,
  minQuality: (value) => `Quality ≥ P${value}`,
  minMomentum: (value) => `Momentum ≥ P${value}`,
};

type Chip = { key: string; value?: string; label: string };

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
  const [, startTransition] = useTransition();

  const remove = useCallback(
    (key: string, value?: string) => {
      const params = new URLSearchParams(searchParams.toString());
      if (value === undefined) {
        params.delete(key);
      } else {
        const kept = params.getAll(key).filter((item) => item !== value);
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
  if (text) chips.push({ key: "q", label: `“${text}”` });

  for (const rating of searchParams.getAll("rating")) {
    chips.push({ key: "rating", value: rating, label: rating });
  }
  for (const sector of searchParams.getAll("sector")) {
    chips.push({ key: "sector", value: sector, label: sector });
  }
  for (const value of searchParams.getAll("eligibility")) {
    chips.push({
      key: "eligibility",
      value,
      label: eligibilityLabel(value),
    });
  }
  for (const [key, label] of Object.entries(TOGGLE_LABELS)) {
    if (searchParams.get(key) === "1") chips.push({ key, label });
  }
  for (const [key, format] of Object.entries(NUMERIC_LABELS)) {
    const value = searchParams.get(key);
    if (value) chips.push({ key, label: format(value) });
  }

  if (!chips.length) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label="Active filters">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        Filtering
      </span>
      {chips.map((chip) => (
        <span
          key={`${chip.key}:${chip.value ?? ""}`}
          className="inline-flex h-7 items-center gap-1 rounded-full border bg-muted pl-2.5 pr-1 text-[11px] font-medium"
        >
          {chip.label}
          <button
            type="button"
            onClick={() => remove(chip.key, chip.value)}
            aria-label={`Remove filter ${chip.label}`}
            className="rounded-full p-0.5 text-muted-foreground transition-colors duration-(--duration-fast) hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="size-3" aria-hidden />
          </button>
        </span>
      ))}
    </div>
  );
}
