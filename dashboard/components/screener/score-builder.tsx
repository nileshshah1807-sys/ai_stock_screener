"use client";

import { useState, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { SlidersHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { PendingMarker } from "@/components/nav-pending";
import { EQUAL_START, SCORE_FACTORS, formatWeights, parseWeights } from "@/lib/custom-score.mjs";

/**
 * "Build your score": the viewer weights the measures they can see and the
 * grid ranks by their mix (lib/custom-score.mjs). It starts from an equal
 * split and offers no other preset, so the order is always the viewer's.
 */
export function ScoreBuilder({ factorModel }: { factorModel: boolean }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();
  const active = parseWeights(searchParams.get("w"));
  const [weights, setWeights] = useState<Record<string, number>>(() => ({ ...EQUAL_START, ...(active ?? {}) }));

  // Percentiles exist only on a factor-model run; there is nothing to weight otherwise.
  if (!factorModel) return null;

  const total = SCORE_FACTORS.reduce((sum, factor) => sum + (weights[factor.key] ?? 0), 0);

  const push = (mutate: (params: URLSearchParams) => void) => {
    const params = new URLSearchParams(searchParams.toString());
    mutate(params);
    params.delete("page");
    startTransition(() => {
      const query = params.toString();
      router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
    });
  };

  const apply = () =>
    push((params) => {
      const mix = formatWeights(weights);
      if (mix) params.set("w", mix);
      else params.delete("w");
      // Rank by the new mix: an earlier column sort would hide it.
      params.delete("sort");
      params.delete("dir");
    });

  const clear = () => {
    setWeights({ ...EQUAL_START });
    push((params) => {
      params.delete("w");
      if (params.get("sort") === "custom_score") params.delete("sort");
    });
  };

  return (
    <>
      <PendingMarker pending={pending} />
      <Popover>
        <PopoverTrigger render={<Button variant={active ? "default" : "outline"} className="gap-1.5" />}>
          <SlidersHorizontal className="size-3.5" aria-hidden />
          <span className="hidden sm:inline">Your score</span>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-80">
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              apply();
            }}
          >
            <div className="space-y-1">
              <p className="text-sm font-semibold">Build your score</p>
              <p className="text-xs text-muted-foreground">
                Choose how much each measure counts. The grid ranks by your mix. This score uses only the
                weights you chose; it is not Cupel&rsquo;s rating or rank.
              </p>
            </div>
            <div className="space-y-3">
              {SCORE_FACTORS.map((factor) => {
                const value = weights[factor.key] ?? 0;
                const share = total ? Math.round((value / total) * 100) : 0;
                const id = `weight-${factor.key}`;
                return (
                  <div key={factor.key} className="space-y-1">
                    <div className="flex items-baseline justify-between text-xs">
                      <label htmlFor={id} className="font-medium">
                        {factor.label}
                      </label>
                      <span className="tabular font-mono text-muted-foreground">{share}%</span>
                    </div>
                    <input
                      id={id}
                      type="range"
                      min={0}
                      max={100}
                      step={5}
                      value={value}
                      onChange={(event) => setWeights((current) => ({ ...current, [factor.key]: Number(event.target.value) }))}
                      className="w-full accent-primary"
                    />
                  </div>
                );
              })}
            </div>
            <p className="text-[11px] leading-snug text-muted-foreground">
              Shares are each weight over the total. A measure a stock lacks is left out and its score is pulled
              toward 50, never counted as zero. Concall outlook is the latest call&rsquo;s 0&ndash;100 score.
            </p>
            <div className="flex items-center justify-between gap-2">
              <Button type="button" variant="ghost" size="sm" onClick={clear} disabled={!active}>
                Clear
              </Button>
              <Button type="submit" size="sm" disabled={!total}>
                Rank by my score
              </Button>
            </div>
          </form>
        </PopoverContent>
      </Popover>
    </>
  );
}
