"use client";

import { useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { SlidersHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { PendingMarker } from "@/components/nav-pending";
import { useUrlDraft } from "@/lib/use-url-draft";
import { cn } from "@/lib/utils";
import { EQUAL_START, POINT_FACTORS, SCORE_FACTORS, formatWeights, parseWeights } from "@/lib/custom-score.mjs";

const byKey = (key: string) => [...SCORE_FACTORS, ...POINT_FACTORS].find((factor) => factor.key === key);

/**
 * "Build your score": the viewer weights the measures they can see and the
 * grid ranks by their mix (lib/custom-score.mjs). It starts from an equal
 * split and offers no other preset, so the order is always the viewer's.
 */
export function ScoreBuilder({ factorModel, concalls }: { factorModel: boolean; concalls: boolean }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();
  const urlMix = searchParams.get("w") ?? "";
  const active = parseWeights(urlMix);
  // A market with no calls (US) offers no call measure: there is nothing to weight.
  const offered = (factor?: { concall?: boolean }) => concalls || !factor?.concall;
  const factors = SCORE_FACTORS.filter(offered);
  const points = POINT_FACTORS.filter(offered);
  // A saved view that sets a mix moves the sliders to it.
  const [weights, setWeights] = useUrlDraft<Record<string, number>>(
    urlMix,
    (url) => Object.fromEntries(Object.entries({ ...EQUAL_START, ...(parseWeights(url) ?? {}) }).filter(([key]) => offered(byKey(key)))),
    formatWeights,
  );

  // Percentiles exist only on a factor-model run; there is nothing to weight otherwise.
  if (!factorModel) return null;

  const total = factors.reduce((sum, factor) => sum + (weights[factor.key] ?? 0), 0);

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
                Choose how much each measure counts. Your mix is ranked across the market on 0&ndash;100, then
                any points you add are applied. This score uses only the settings you chose; it is not
                Cupel&rsquo;s rating or rank.
              </p>
            </div>
            <div className="space-y-3">
              {factors.map((factor) => {
                const value = weights[factor.key] ?? 0;
                const id = `weight-${factor.key}`;
                return (
                  <div key={factor.key} className="space-y-1">
                    <div className="flex items-baseline justify-between text-xs">
                      <label htmlFor={id} className="font-medium">
                        {factor.label}
                      </label>
                      <span className="tabular font-mono text-muted-foreground">{value}%</span>
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
              {/* Each slider shows the weight as set; the score uses each weight's share of the
                  total, so a total other than 100 is scaled, never an error. */}
              <p className="flex items-baseline justify-between text-xs" aria-live="polite">
                <span className="font-medium">Total</span>
                <span className={cn("tabular font-mono", total === 100 ? "text-muted-foreground" : "text-foreground")}>
                  {total}%{total && total !== 100 ? " · scaled to 100" : ""}
                </span>
              </p>
            </div>
            <div className="space-y-3 border-t pt-3">
              {points.map((factor) => {
                const value = weights[factor.key] ?? 0;
                const id = `points-${factor.key}`;
                return (
                  <div key={factor.key} className="space-y-1">
                    <div className="flex items-baseline justify-between text-xs">
                      <label htmlFor={id} className="font-medium">
                        {factor.label}
                      </label>
                      <span className="tabular font-mono text-muted-foreground">{value ? `×${(value / 100).toFixed(2)}` : "off"}</span>
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
              A total other than 100% is scaled, so each weight counts as its share of the total. A measure a stock lacks counts as 50, never as zero.
              Valuation points: the multiple times the valuation score&rsquo;s distance from 50.
              {concalls
                ? " Concall points: the multiple times how far a call in the last 180 days sits from the market\u2019s median call (85% outlook, 15% tone), fading by half every 90 days."
                : null}
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
