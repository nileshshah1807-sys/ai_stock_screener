"use client";

import { useState, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Info, SlidersHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { PendingMarker } from "@/components/nav-pending";
import { useMarket, useRunDate } from "@/components/market-provider";
import { useScorePreview, type Preview } from "@/lib/use-score-preview";
import { useUrlDraft } from "@/lib/use-url-draft";
import { formatScore } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  EQUAL_START,
  IMPORTANCE,
  POINT_FACTORS,
  SCORE_FACTORS,
  formatWeights,
  importanceStep,
  importanceText,
  mixShares,
  parseWeights,
} from "@/lib/custom-score.mjs";

const byKey = (key: string) => [...SCORE_FACTORS, ...POINT_FACTORS].find((factor) => factor.key === key);

type Factor = { key: string; label: string; caption: string; about: string };

// One hue at falling strength, a gap between segments and a written legend: colour is never the only cue.
const SEGMENT = ["bg-primary", "bg-primary/80", "bg-primary/60", "bg-primary/45", "bg-primary/35", "bg-primary/25", "bg-primary/15"];

/**
 * "Build your score": the viewer says how much each measure matters to them
 * and the grid sorts by their mix (lib/custom-score.mjs). It starts from an
 * equal split and offers no other preset, so the order is always the viewer's.
 * The preview of the first five is worked out in the browser, never on the server.
 */
export function ScoreBuilder({ factorModel, concalls }: { factorModel: boolean; concalls: boolean }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const market = useMarket();
  const runDate = useRunDate();
  const [pending, startTransition] = useTransition();
  const [open, setOpen] = useState(false);
  const urlMix = searchParams.get("w") ?? "";
  const active = parseWeights(urlMix);
  // A market with no calls (US) offers no call measure: there is nothing to weight.
  const offered = (factor?: { concall?: boolean }) => concalls || !factor?.concall;
  const factors: Factor[] = SCORE_FACTORS.filter(offered);
  const points: Factor[] = POINT_FACTORS.filter(offered);
  // A saved view that sets a mix moves the controls to it.
  const [weights, setWeights, pushedMix] = useUrlDraft<Record<string, number>>(
    urlMix,
    (url) => Object.fromEntries(Object.entries({ ...EQUAL_START, ...(parseWeights(url) ?? {}) }).filter(([key]) => offered(byKey(key)))),
    formatWeights,
  );
  const preview = useScorePreview(open && factorModel, market.code, runDate, weights);

  // Percentiles exist only on a factor-model run; there is nothing to weight otherwise.
  if (!factorModel) return null;

  const shares = mixShares(weights, factors);
  const shareOf = (key: string) => shares.find((entry) => entry.key === key)?.share ?? 0;
  const empty = !shares.length;

  const push = (mutate: (params: URLSearchParams) => void) => {
    const params = new URLSearchParams(searchParams.toString());
    mutate(params);
    params.delete("page");
    startTransition(() => {
      const query = params.toString();
      router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
    });
  };

  const apply = () => {
    push((params) => {
      const mix = formatWeights(weights);
      if (mix !== urlMix) pushedMix(mix); // a push that changes nothing never lands
      if (mix) params.set("w", mix);
      else params.delete("w");
      // Sort by the new mix, whatever column the grid was sorted by.
      params.set("sort", "custom_score");
      params.delete("dir");
    });
    setOpen(false);
  };

  const reset = () => {
    setWeights({ ...EQUAL_START });
    if (urlMix) pushedMix("");
    push((params) => {
      params.delete("w");
      if (params.get("sort") === "custom_score") params.delete("sort");
    });
  };

  const set = (key: string, value: number) => setWeights((current) => ({ ...current, [key]: value }));

  return (
    <>
      <PendingMarker pending={pending} />
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger render={<Button variant={active ? "default" : "outline"} className="gap-1.5" />}>
          <SlidersHorizontal className="size-3.5" aria-hidden />
          <span>{active ? "Your score · on" : "Your score"}</span>
        </PopoverTrigger>
        <PopoverContent align="end" className="max-h-[min(80vh,44rem)] w-[min(24rem,calc(100vw-2rem))] overflow-y-auto">
          <form
            className="space-y-4"
            aria-labelledby="score-builder-title"
            onSubmit={(event) => {
              event.preventDefault();
              apply();
            }}
          >
            <div className="space-y-1">
              <h2 id="score-builder-title" className="text-sm font-semibold">
                Build your score
              </h2>
              <p className="text-xs text-muted-foreground">Say how much each measure matters to you. The list re-sorts by your mix.</p>
            </div>

            <MixBar factors={factors} shares={shares} />

            <ul className="space-y-3">
              {factors.map((factor) => (
                <li key={factor.key}>
                  <ImportanceControl
                    factor={factor}
                    value={weights[factor.key] ?? 0}
                    share={shareOf(factor.key)}
                    onChange={(next) => set(factor.key, next)}
                  />
                </li>
              ))}
            </ul>

            <PreviewList preview={preview} empty={empty} />

            {points.length ? (
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
                        <span className="tabular font-mono text-muted-foreground">{value ? `×${(value / 100).toFixed(2)}` : "Off"}</span>
                      </div>
                      <p className="text-xs text-muted-foreground">{factor.caption}</p>
                      <input
                        id={id}
                        type="range"
                        min={0}
                        max={100}
                        step={5}
                        value={value}
                        aria-valuetext={value ? `${factor.label}: ${(value / 100).toFixed(2)} times` : `${factor.label}: off`}
                        onChange={(event) => set(factor.key, Number(event.target.value))}
                        className="w-full accent-primary"
                      />
                    </div>
                  );
                })}
              </div>
            ) : null}

            <div className="space-y-2 border-t pt-3">
              <p className="text-xs text-muted-foreground">
                Missing data counts as middle of the pack, never as zero. Your settings, your score: not a Cupel rating or advice.
              </p>
              {empty ? (
                <p className="text-xs font-medium" role="status">
                  Give at least one measure some weight to build a score.
                </p>
              ) : null}
              <div className="flex items-center justify-between gap-2">
                <Button type="button" variant="ghost" size="sm" onClick={reset} disabled={!active}>
                  Reset to equal
                </Button>
                <Button type="submit" size="sm" disabled={empty}>
                  Sort by my score
                </Button>
              </div>
            </div>
          </form>
        </PopoverContent>
      </Popover>
    </>
  );
}

/** Each measure's real share of the mix, felt as it changes. */
function MixBar({ factors, shares }: { factors: Factor[]; shares: { key: string; share: number }[] }) {
  const tone = (key: string) => SEGMENT[factors.findIndex((factor) => factor.key === key)] ?? SEGMENT.at(-1);
  const label = (key: string) => factors.find((factor) => factor.key === key)?.label ?? key;
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium">Your mix</p>
      <div className="flex h-2 gap-0.5 overflow-hidden rounded-full bg-muted" aria-hidden>
        {shares.map((entry) => (
          <div
            key={entry.key}
            className={cn("h-full transition-[flex-grow] duration-200 ease-out motion-reduce:transition-none", tone(entry.key))}
            style={{ flexGrow: entry.share, flexBasis: 0 }}
          />
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        {shares.length ? shares.map((entry) => `${label(entry.key)} ${entry.share}%`).join(" · ") : "Nothing weighted yet"}
      </p>
    </div>
  );
}

/** One measure: its name, what it means, and how much it counts, in words. */
function ImportanceControl({
  factor,
  value,
  share,
  onChange,
}: {
  factor: Factor;
  value: number;
  share: number;
  onChange: (value: number) => void;
}) {
  const [explained, setExplained] = useState(false);
  const id = `weight-${factor.key}`;
  const step = importanceStep(value);
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="flex items-center gap-1">
          <label htmlFor={id} className="font-medium">
            {factor.label}
          </label>
          <button
            type="button"
            className="-my-1.5 inline-flex size-7 items-center justify-center rounded-full text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
            aria-expanded={explained}
            aria-controls={`${id}-about`}
            aria-label={`What is ${factor.label}?`}
            onClick={() => setExplained((shown) => !shown)}
          >
            <Info className="size-3.5" aria-hidden />
          </button>
        </span>
        <span className="tabular text-muted-foreground">
          {IMPORTANCE[step].label}
          {value > 0 ? <span className="ml-1.5 font-mono text-foreground">{share}%</span> : null}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">{factor.caption}</p>
      {explained ? (
        <p id={`${id}-about`} className="rounded-md bg-muted px-2.5 py-2 text-xs leading-relaxed">
          {factor.about}
        </p>
      ) : null}
      {/* A value between steps (an older link) shows as the nearer step and is kept until moved. */}
      <input
        id={id}
        type="range"
        min={0}
        max={IMPORTANCE.length - 1}
        step={1}
        value={step}
        aria-valuetext={importanceText(factor.label, value, share)}
        onChange={(event) => onChange(IMPORTANCE[Number(event.target.value)].value)}
        className="h-6 w-full accent-primary"
      />
      <div className="flex justify-between text-[11px] text-muted-foreground" aria-hidden>
        <span>Ignore</span>
        <span>Most</span>
      </div>
    </div>
  );
}

/** The first five by the draft mix, so a change is seen before it is applied. */
function PreviewList({ preview, empty }: { preview: Preview; empty: boolean }) {
  return (
    <div className="space-y-1.5 rounded-md border px-3 py-2.5">
      <p className="text-xs font-medium">Top 5 by your mix</p>
      {empty ? (
        <p className="text-xs text-muted-foreground">Weight a measure to see the list.</p>
      ) : preview.state === "failed" ? (
        <p className="text-xs text-muted-foreground">The preview could not load. Sorting still works.</p>
      ) : preview.state === "loading" ? (
        <p className="text-xs text-muted-foreground">Working out your list…</p>
      ) : (
        <ol className="space-y-0.5 text-xs">
          {preview.top.map((row, at) => (
            <li key={row.symbol} className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 truncate">
                <span className="tabular mr-1.5 text-muted-foreground">{at + 1}</span>
                {row.company ?? row.symbol}
              </span>
              <span className="tabular shrink-0 font-mono text-muted-foreground">{formatScore(row.score)}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
