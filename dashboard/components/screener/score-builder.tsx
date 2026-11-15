"use client";

import { useEffect, useRef, useState, useSyncExternalStore, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ChevronRight, Info, Minus, Plus, Scale, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
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

const byKey = (key: string) => [...SCORE_FACTORS, ...POINT_FACTORS].find((factor) => factor.key === key);

type Factor = { key: string; label: string; caption: string; about: string };
type Shares = { key: string; share: number }[];

// One hue at falling strength, a hairline between segments and a written legend: colour is never the only cue.
const SEGMENT = ["bg-primary", "bg-primary/80", "bg-primary/60", "bg-primary/45", "bg-primary/35", "bg-primary/25", "bg-primary/15"];
// The five measures every viewer starts with; the rest wait behind "More measures".
const MAIN = new Set(["q", "g", "m", "v", "r"]);
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
// The header is one 3.5rem row from xl up (components/app-shell.tsx); below that the panel is a bottom sheet.
const useWide = mediaStore("(min-width: 80rem)");
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
 * On a wide screen it is a side panel the grid makes room for
 * (globals.css, [data-score-panel]); on a narrow one, a bottom sheet.
 */
export function ScoreBuilder({ factorModel, concalls }: { factorModel: boolean; concalls: boolean }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const market = useMarket();
  const runDate = useRunDate();
  const wide = useWide();
  const [pending, startTransition] = useTransition();
  const [open, setOpen] = useState(false);
  const [said, setSaid] = useState("");
  // The measure just changed, lit for a moment so the viewer sees what moved every share.
  const [changed, setChanged] = useState<{ key: string; at: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const sheet = useRef<HTMLDivElement>(null);
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
    setChanged({ key, at: Date.now() });
  };
  // A stepper says what it did; the slider already says it through aria-valuetext.
  const stepTo = (factor: Factor, value: number) => {
    set(factor.key, value);
    const next = mixShares({ ...weights, [factor.key]: value }, factors);
    setSaid(importanceText(factor.label, value, next.find((entry) => entry.key === factor.key)?.share ?? 0));
  };

  const control = (factor: Factor) => (
    <li key={factor.key}>
      <ImportanceControl
        factor={factor}
        value={weights[factor.key] ?? 0}
        share={shareOf(factor.key)}
        lit={changed?.key === factor.key}
        onChange={(next) => set(factor.key, next)}
        onStep={(next) => stepTo(factor, next)}
      />
    </li>
  );

  const form = (title: React.ReactNode, description: React.ReactNode) => (
    <form
      className="flex min-h-0 flex-1 flex-col"
      onSubmit={(event) => {
        event.preventDefault();
        apply();
      }}
    >
      <div className="space-y-1 px-5 pt-5 pr-16">
        {title}
        {description}
      </div>
      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto overscroll-contain px-5 pt-4 pb-6">
        <PreviewList preview={preview} empty={empty} />
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
      </div>
      {/* Pinned under the scroll, so Apply is always one tap away. */}
      <div className="space-y-3 border-t px-5 pt-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
        {empty ? <p className="text-xs font-medium">{NOTHING_WEIGHTED}</p> : null}
        <div className="flex items-center justify-between gap-2">
          <Button type="button" variant="ghost" className="-ml-3 h-11" onClick={reset} disabled={!resettable}>
            Reset to equal
          </Button>
          <Button type="submit" className="h-11 px-5" disabled={empty}>
            Sort by my score
          </Button>
        </div>
        <p className="text-xs leading-relaxed text-muted-foreground">
          Your score uses only the weights you choose. Missing data counts as middle of the pack, never as zero. Not advice.
        </p>
      </div>
      {/* The panel's one polite voice: what a stepper or reset just did, or why nothing can apply. */}
      <p className="sr-only" aria-live="polite">
        {empty ? NOTHING_WEIGHTED : said}
      </p>
    </form>
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

      {wide ? (
        open ? (
          <SidePanel onClose={close}>
            {form(
              <h2 id="score-builder-title" className="text-base font-semibold">
                {TITLE}
              </h2>,
              <p className="text-xs leading-relaxed text-muted-foreground">{DESCRIPTION}</p>,
            )}
          </SidePanel>
        ) : null
      ) : (
        <Sheet open={open} onOpenChange={(next) => (next ? setOpen(true) : close())}>
          <SheetContent
            ref={sheet}
            side="bottom"
            className="max-h-[85dvh] gap-0 p-0 outline-none"
            // A tap opens on the sheet itself, not a ring on its first button; the keyboard still lands on a control.
            initialFocus={(how) => (how === "keyboard" ? true : sheet.current)}
          >
            {form(
              <SheetTitle className="text-base">{TITLE}</SheetTitle>,
              <SheetDescription className="text-xs leading-relaxed">{DESCRIPTION}</SheetDescription>,
            )}
          </SheetContent>
        </Sheet>
      )}
    </>
  );
}

/**
 * The wide-screen panel: beside the grid rather than over it, so the list it
 * re-sorts stays in view. Not modal: the page stays usable, Escape closes it.
 */
function SidePanel({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });
  useEffect(() => {
    panel.current?.focus();
    // Only an Escape meant for the panel: not one a menu or the search box elsewhere already used.
    const onKey = (event: KeyboardEvent) => {
      const inside = event.target instanceof Node && panel.current?.contains(event.target);
      if (event.key === "Escape" && inside && !event.defaultPrevented) closeRef.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div
      ref={panel}
      data-score-panel
      role="dialog"
      aria-modal="false"
      aria-labelledby="score-builder-title"
      tabIndex={-1}
      className="fixed top-14 right-0 bottom-0 z-20 flex w-[25rem] flex-col border-l bg-card text-sm shadow-[-8px_0_24px_-12px_rgb(0_0_0/0.18)] outline-none"
    >
      <Button type="button" variant="ghost" size="icon" className="absolute top-3 right-3 size-11" onClick={onClose} aria-label="Close">
        <X className="size-4" aria-hidden />
      </Button>
      {children}
    </div>
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
  onChange,
  onStep,
}: {
  factor: Factor;
  value: number;
  share: number;
  lit: boolean;
  onChange: (value: number) => void;
  onStep: (value: number) => void;
}) {
  const [explained, setExplained] = useState(false);
  const id = `weight-${factor.key}`;
  const step = importanceStep(value);
  const last = IMPORTANCE.length - 1;
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
        <span className="text-xs text-muted-foreground">
          {IMPORTANCE[step].label}
          {value > 0 ? <Percent value={share} className="ml-2 inline-block min-w-[3ch] text-right text-foreground" /> : null}
        </span>
      </div>
      <p className="-mt-1 text-xs leading-relaxed text-muted-foreground">{factor.caption}</p>
      {explained ? (
        <p id={`${id}-about`} className="mt-2 rounded-md bg-muted px-3 py-2 text-xs leading-relaxed">
          {factor.about}
        </p>
      ) : null}
      <div className="mt-1 flex items-center gap-1">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="-ml-2 size-11 shrink-0 rounded-full text-muted-foreground hover:text-foreground"
          disabled={step === 0}
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
          aria-valuetext={importanceText(factor.label, value, share)}
          onChange={(event) => onChange(IMPORTANCE[Number(event.target.value)].value)}
          className="score-range h-11 min-w-0 flex-1"
          style={{ "--fill": step / last } as React.CSSProperties}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="-mr-2 size-11 shrink-0 rounded-full text-muted-foreground hover:text-foreground"
          disabled={step === last}
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
function PreviewList({ preview, empty }: { preview: Preview; empty: boolean }) {
  const quiet = "text-xs text-muted-foreground";
  return (
    <section aria-labelledby="score-preview-title" className="space-y-2 rounded-lg bg-muted/50 px-3 py-3">
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
