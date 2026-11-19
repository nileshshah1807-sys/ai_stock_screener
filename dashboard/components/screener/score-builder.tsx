"use client";

import { useEffect, useRef, useState, useSyncExternalStore, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ChevronRight, Info, Minus, Plus, Scale } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { PanelSheet } from "@/components/panel-sheet";
import { SegmentedControl } from "@/components/segmented-control";
import { PendingMarker } from "@/components/nav-pending";
import { useMarket, useRunDate } from "@/components/market-provider";
import { useScorePreview, type Preview } from "@/lib/use-score-preview";
import { useUrlDraft } from "@/lib/use-url-draft";
import { formatScore } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  EQUAL_START,
  IMPORTANCE,
  NUDGE,
  POINT_FACTORS,
  SCORE_FACTORS,
  formatWeights,
  importanceStep,
  importanceText,
  mixShares,
  nudgeStep,
  parseWeights,
} from "@/lib/custom-score.mjs";

type Factor = { key: string; label: string; caption: string; about: string; toggle?: boolean };
type Shares = { key: string; share: number }[];

// One hue at falling strength, a hairline between segments and a written legend: colour is never the only cue.
const SEGMENT = ["bg-primary", "bg-primary/80", "bg-primary/60", "bg-primary/45", "bg-primary/35", "bg-primary/25", "bg-primary/15"];
// The five measures every viewer starts with, and the Earnings call behind its switch; the rest wait behind "More measures".
const MAIN = new Set(["q", "g", "m", "v", "r", "c"]);
// Where a switched-on measure starts: the middle step.
const SWITCH_ON = 20;
const SHIFT_MS = 220;
const HIGHLIGHT_MS = 1400;

function mediaStore(query: string) {
  const subscribe = (change: () => void) => {
    const list = window.matchMedia(query);
    list.addEventListener("change", change);
    return () => list.removeEventListener("change", change);
  };
  return () => useSyncExternalStore(subscribe, () => window.matchMedia(query).matches, () => false);
}
const useReducedMotion = mediaStore("(prefers-reduced-motion: reduce)");

/** A number that glides to its new value (ease-out, requestAnimationFrame), so a shift in the mix is seen happening. */
function useEased(target: number) {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(target);
  const at = useRef(target);
  useEffect(() => {
    const from = at.current;
    if (reduced || from === target) {
      at.current = target;
      return;
    }
    const start = performance.now();
    let frame = requestAnimationFrame(function tick(now) {
      const t = Math.min(1, (now - start) / SHIFT_MS);
      at.current = from + (target - from) * (1 - (1 - t) ** 3);
      setShown(at.current);
      if (t < 1) frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  }, [target, reduced]);
  return reduced ? target : Math.round(shown);
}

const TITLE = "Build your score";
const DESCRIPTION = "Say how much each measure matters to you. The list sorts by your mix.";
const NOTHING_WEIGHTED = "Give at least one measure some weight to build a score.";

/**
 * "Build your score": the viewer says how much each measure matters to them
 * and the grid sorts by their mix (lib/custom-score.mjs). It starts from an
 * equal split and offers no other preset, so the order is always the viewer's.
 * The preview of the first five is worked out in the browser, never on the server.
 * It opens in the app's one panel (components/panel-sheet.tsx), as Filters does.
 */
export function ScoreBuilder({ factorModel }: { factorModel: boolean }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const market = useMarket();
  const runDate = useRunDate();
  const [pending, startTransition] = useTransition();
  const [open, setOpen] = useState(false);
  const [said, setSaid] = useState("");
  // The measure just changed, lit for a moment so the viewer sees what moved every share.
  const [changed, setChanged] = useState<{ key: string } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const start = useRef<HTMLElement>(null);
  const urlMix = searchParams.get("w") ?? "";
  const active = parseWeights(urlMix);
  const factors: Factor[] = SCORE_FACTORS;
  const points: Factor[] = POINT_FACTORS;
  // A saved view that sets a mix moves the controls to it.
  const [weights, setWeights, pushedMix] = useUrlDraft<Record<string, number>>(
    urlMix,
    (url) => ({ ...EQUAL_START, ...(parseWeights(url) ?? {}) }),
    formatWeights,
  );
  const preview = useScorePreview(open && factorModel, market.code, runDate, weights);
  // A switched measure stays on at Ignore; a link that weights it opens with it on.
  const [switchedOn, setSwitchedOn] = useState<Record<string, boolean>>({});
  const isOn = (key: string) => switchedOn[key] ?? (weights[key] ?? 0) > 0;
  const lastOn = useRef<Record<string, number>>({});

  useEffect(() => {
    if (!changed) return;
    const fade = setTimeout(() => setChanged(null), HIGHLIGHT_MS);
    return () => clearTimeout(fade);
  }, [changed]);

  // Percentiles exist only on a factor-model run; there is nothing to weight otherwise.
  if (!factorModel) return null;

  const shares = mixShares(weights, factors);
  const shareOf = (key: string) => shares.find((entry) => entry.key === key)?.share ?? 0;
  const empty = !shares.length;
  // Reset is live whenever there is something to reset: an applied mix, or a draft moved off the equal start.
  const resettable = Boolean(active) || formatWeights(weights) !== formatWeights(EQUAL_START);
  const main = factors.filter((factor) => MAIN.has(factor.key));
  const more = factors.filter((factor) => !MAIN.has(factor.key));

  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };

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
    close();
  };

  const reset = () => {
    setWeights({ ...EQUAL_START });
    setSwitchedOn({});
    setChanged(null);
    setSaid("Reset to an equal mix.");
    if (urlMix) pushedMix("");
    push((params) => {
      params.delete("w");
      if (params.get("sort") === "custom_score") params.delete("sort");
    });
  };

  const set = (key: string, value: number) => {
    if ((weights[key] ?? 0) === value) return;
    setWeights((current) => ({ ...current, [key]: value }));
    setChanged({ key }); // a fresh object restarts the fade even for the same measure
  };
  // A stepper says what it did; the slider already says it through aria-valuetext.
  const stepTo = (factor: Factor, value: number) => {
    set(factor.key, value);
    const next = mixShares({ ...weights, [factor.key]: value }, factors);
    setSaid(importanceText(factor.label, value, next.find((entry) => entry.key === factor.key)?.share ?? 0));
  };

  // Off adds nothing and remembers the step; on brings it back (the middle step the first time).
  const switchTo = (factor: Factor, on: boolean) => {
    const current = weights[factor.key] ?? 0;
    if (!on && current > 0) lastOn.current[factor.key] = current;
    const next = on ? (lastOn.current[factor.key] ?? SWITCH_ON) : 0;
    setSwitchedOn((state) => ({ ...state, [factor.key]: on }));
    set(factor.key, next);
    setSaid(on ? importanceText(factor.label, next, mixShares({ ...weights, [factor.key]: next }, factors).find((entry) => entry.key === factor.key)?.share ?? 0) : `${factor.label}: Off`);
  };

  const control = (factor: Factor) => (
    <li key={factor.key}>
      <ImportanceControl
        factor={factor}
        value={weights[factor.key] ?? 0}
        share={shareOf(factor.key)}
        lit={changed?.key === factor.key}
        on={factor.toggle ? isOn(factor.key) : undefined}
        onSwitch={(on) => switchTo(factor, on)}
        onChange={(next) => set(factor.key, next)}
        onStep={(next) => stepTo(factor, next)}
      />
    </li>
  );

  return (
    <>
      <PendingMarker pending={pending} />
      <Button
        ref={trigger}
        variant={active ? "default" : "outline"}
        className="gap-1.5"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => (open ? close() : setOpen(true))}
      >
        <Scale className={cn("size-3.5", pending && "animate-pulse motion-reduce:animate-none")} aria-hidden />
        {/* Until the sorted rows land, the button says so: a slow sort never reads as a no-op. */}
        <span aria-live="polite">{pending ? "Sorting…" : active ? "Your score · on" : "Your score"}</span>
      </Button>

      <PanelSheet
        open={open}
        onOpenChange={(next) => (next ? setOpen(true) : close())}
        title={TITLE}
        description={DESCRIPTION}
        // A tap opens on the panel's first section, not a ring on its first button; the keyboard still lands on a control.
        initialFocus={(how) => (how === "keyboard" ? true : start.current)}
        note={empty ? NOTHING_WEIGHTED : "Only your weights. Not advice."}
        actions={
          <>
            <Button type="button" variant="ghost" className="h-11 px-3" onClick={reset} disabled={!resettable}>
              Reset to equal
            </Button>
            <Button type="button" className="h-11 px-5" onClick={apply} disabled={empty}>
              Sort by my score
            </Button>
          </>
        }
      >
        <div className="space-y-6 pt-4 pb-6">
          <PreviewList preview={preview} empty={empty} start={start} />
          <section aria-labelledby="score-mix-title" className="space-y-3">
            <MixBar factors={factors} shares={shares} lit={changed?.key ?? null} />
            <ul className="-mx-2 space-y-1">{main.map(control)}</ul>
            {more.length ? (
              <Disclosure title="More measures" on={more.some((factor) => (weights[factor.key] ?? 0) > 0)}>
                <ul className="-mx-2 space-y-1">{more.map(control)}</ul>
              </Disclosure>
            ) : null}
          </section>
          {points.length ? (
            <Disclosure title="Extra nudges" on={points.some((factor) => (weights[factor.key] ?? 0) > 0)}>
              <div className="space-y-5">
                {points.map((factor) => (
                  <Nudge key={factor.key} factor={factor} value={weights[factor.key] ?? 0} onChange={(next) => set(factor.key, next)} />
                ))}
              </div>
            </Disclosure>
          ) : null}
          <p className="text-xs leading-relaxed text-muted-foreground">
            Your score uses only the weights you choose. Missing data counts as middle of the pack, never as zero. A score is
            where a stock lands among all of them: 100 is first, 0 is last.
          </p>
          {/* What a stepper or reset just did; the footer note speaks for the rest. */}
          <p className="sr-only" aria-live="polite">
            {said}
          </p>
        </div>
      </PanelSheet>
    </>
  );
}

/** A collapsed group, open on arrival when something in it is already on. */
function Disclosure({ title, on, children }: { title: string; on: boolean; children: React.ReactNode }) {
  // Decided once: turning the last item off must not fold the group shut under the pointer.
  const [startOpen] = useState(on);
  return (
    <details className="group/more border-t" open={startOpen || undefined}>
      <summary className="-mx-2 flex min-h-11 cursor-pointer items-center justify-between rounded-md px-2 text-sm font-medium marker:content-none hover:bg-muted/60 focus-visible:outline-2 focus-visible:outline-ring">
        {title}
        <span className="text-xs font-normal text-muted-foreground">
          {on ? "On" : "Off"}
          <ChevronRight
            aria-hidden
            className="ml-1.5 inline-block size-4 align-[-3px] transition-transform duration-200 ease-out group-open/more:rotate-90 motion-reduce:transition-none"
          />
        </span>
      </summary>
      <div className="pt-2">{children}</div>
    </details>
  );
}

/** Each measure's real share of the mix, felt as it changes: segments glide, numbers count. */
function MixBar({ factors, shares, lit }: { factors: Factor[]; shares: Shares; lit: string | null }) {
  const shareOf = (key: string) => shares.find((entry) => entry.key === key)?.share ?? 0;
  const weighted = factors.filter((factor) => shareOf(factor.key) > 0);
  return (
    <div className="space-y-2">
      <h3 id="score-mix-title" className="text-sm font-medium">
        How much each counts
      </h3>
      {/* Every measure keeps its segment, at zero width when ignored, so a change glides instead of popping. */}
      <div className="flex h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
        {factors.map((factor, at) => (
          <div
            key={factor.key}
            className={cn(
              "h-full shadow-[inset_-2px_0_0_var(--color-card)] transition-[flex-grow,opacity] duration-[220ms] ease-out motion-reduce:transition-none",
              SEGMENT[at] ?? SEGMENT.at(-1),
              lit && lit !== factor.key && "opacity-60",
            )}
            style={{ flexGrow: shareOf(factor.key), flexBasis: 0 }}
          />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {weighted.length ? (
          weighted.map((factor) => (
            <li key={factor.key} className={cn("transition-colors duration-300", lit === factor.key && "font-medium text-foreground")}>
              {factor.label} <Percent value={shareOf(factor.key)} />
            </li>
          ))
        ) : (
          <li>Nothing weighted yet</li>
        )}
      </ul>
    </div>
  );
}

function Percent({ value, className }: { value: number; className?: string }) {
  return <span className={cn("tabular font-mono", className)}>{useEased(value)}%</span>;
}

/** One measure: its name, what it means, and how much it counts, in words. */
function ImportanceControl({
  factor,
  value,
  share,
  lit,
  on,
  onSwitch,
  onChange,
  onStep,
}: {
  factor: Factor;
  value: number;
  share: number;
  lit: boolean;
  /** Set for a measure behind a switch: off, the slider shows but adds nothing. */
  on?: boolean;
  onSwitch?: (on: boolean) => void;
  onChange: (value: number) => void;
  onStep: (value: number) => void;
}) {
  const [explained, setExplained] = useState(false);
  const id = `weight-${factor.key}`;
  const step = importanceStep(value);
  const last = IMPORTANCE.length - 1;
  const off = on === false;
  return (
    <div
      className={cn(
        "rounded-lg px-2 py-2 transition-colors duration-500 ease-out motion-reduce:transition-none",
        lit ? "bg-primary/[0.06]" : "bg-transparent",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center">
          <label htmlFor={id} className="text-sm font-medium">
            {factor.label}
          </label>
          <button
            type="button"
            className="-my-2 inline-flex size-11 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring aria-expanded:text-foreground"
            aria-expanded={explained}
            aria-controls={`${id}-about`}
            aria-label={`What is ${factor.label}?`}
            onClick={() => setExplained((shown) => !shown)}
          >
            <Info className="size-3.5" aria-hidden />
          </button>
        </span>
        <span className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>
            {off ? "Off" : IMPORTANCE[step].label}
            {value > 0 ? <Percent value={share} className="ml-2 inline-block min-w-[3ch] text-right text-foreground" /> : null}
          </span>
          {on === undefined ? null : (
            <Switch checked={on} onCheckedChange={(checked) => onSwitch?.(checked)} aria-label={`Use ${factor.label}`} />
          )}
        </span>
      </div>
      <p className="-mt-1 text-xs leading-relaxed text-muted-foreground">{factor.caption}</p>
      {explained ? (
        <p id={`${id}-about`} className="mt-2 rounded-md bg-muted px-3 py-2 text-xs leading-relaxed">
          {factor.about}
        </p>
      ) : null}
      {/* Off: shown, dimmed and inert, so the viewer sees what the switch turns on. */}
      <div
        className={cn("mt-1 flex items-center gap-1 transition-opacity duration-200 ease-out motion-reduce:transition-none", off && "opacity-40")}
      >
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="-ml-2 size-11 shrink-0 rounded-full text-muted-foreground hover:text-foreground"
          disabled={off || step === 0}
          aria-label={`Less ${factor.label}`}
          onClick={() => onStep(IMPORTANCE[step - 1].value)}
        >
          <Minus className="size-4" aria-hidden />
        </Button>
        {/* A value between steps (an older link) shows as the nearer step and is kept until moved. */}
        <input
          id={id}
          type="range"
          min={0}
          max={last}
          step={1}
          value={step}
          aria-valuetext={off ? `${factor.label}: Off` : importanceText(factor.label, value, share)}
          aria-disabled={off || undefined}
          onChange={(event) => (off ? undefined : onChange(IMPORTANCE[Number(event.target.value)].value))}
          className={cn("score-range h-11 min-w-0 flex-1", off && "cursor-not-allowed")}
          style={{ "--fill": step / last } as React.CSSProperties}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="-mr-2 size-11 shrink-0 rounded-full text-muted-foreground hover:text-foreground"
          disabled={off || step === last}
          aria-label={`More ${factor.label}`}
          onClick={() => onStep(IMPORTANCE[step + 1].value)}
        >
          <Plus className="size-4" aria-hidden />
        </Button>
      </div>
    </div>
  );
}

/** Points on top of the mix, in three words rather than a multiplier. */
function Nudge({ factor, value, onChange }: { factor: Factor; value: number; onChange: (value: number) => void }) {
  const chosen = NUDGE[nudgeStep(value)].label;
  return (
    <div className="space-y-2">
      <div>
        <p className="text-sm font-medium">{factor.label}</p>
        <p className="text-xs leading-relaxed text-muted-foreground">{factor.caption}</p>
      </div>
      <SegmentedControl
        label={factor.label}
        size="md"
        value={chosen}
        onChange={(label) => onChange(NUDGE.find((option) => option.label === label)?.value ?? 0)}
        options={NUDGE.map((option) => ({ value: option.label, label: option.label }))}
      />
    </div>
  );
}

/** The first five of the whole market by the draft mix, so a change is seen before it is applied. */
function PreviewList({ preview, empty, start }: { preview: Preview; empty: boolean; start: React.RefObject<HTMLElement | null> }) {
  const quiet = "text-xs text-muted-foreground";
  return (
    <section ref={start} tabIndex={-1} aria-labelledby="score-preview-title" className="space-y-2 rounded-lg bg-muted/50 px-3 py-3 outline-none">
      <div className="flex items-baseline justify-between gap-3">
        <h3 id="score-preview-title" className="text-sm font-medium">
          Top 5 on your mix
        </h3>
        {/* The grid below may be filtered; this list never is, so it says so. */}
        <span className={quiet}>Whole market, before filters</span>
      </div>
      {empty ? (
        <p className={quiet}>Weight a measure to see the list.</p>
      ) : preview.state === "failed" ? (
        <p className={quiet}>The preview could not load. Sorting still works.</p>
      ) : preview.state === "loading" ? (
        <ol className="space-y-1.5" aria-label="Working out your list">
          {[0, 1, 2, 3, 4].map((at) => (
            <li key={at} className="h-4 animate-pulse rounded bg-muted motion-reduce:animate-none" />
          ))}
        </ol>
      ) : preview.top.length ? (
        <ol className="space-y-1 text-sm">
          {preview.top.map((row, at) => (
            <li key={row.symbol} className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 truncate">
                <span className="tabular mr-2 inline-block w-3 text-xs text-muted-foreground">{at + 1}</span>
                {row.company ?? row.symbol}
              </span>
              <span className="tabular shrink-0 font-mono text-xs text-muted-foreground">{formatScore(row.score)}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className={quiet}>No rated stocks on this run.</p>
      )}
    </section>
  );
}
