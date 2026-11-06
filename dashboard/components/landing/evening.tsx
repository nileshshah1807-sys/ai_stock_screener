"use client";

import { useRef } from "react";

import { useScene } from "@/components/landing/use-scene";
import { EVENING, TONE } from "@/lib/landing.mjs";
import { cn } from "@/lib/utils";

const span = TONE.max - TONE.min;
const pct = (v: number) => `${((v - TONE.min) / span) * 100}%`;
const edges: number[] = [TONE.min, ...TONE.cuts.map(([cut]) => Number(cut)), TONE.max];

/**
 * An example evening, left to right: results are filed, their card appears,
 * the call is read, the bell tells you. Beneath it, the scale a call's tone is
 * read on, drawn to the app's real cut points with the median call marked.
 * The call is invented and the scale is neutral ink.
 */
export function Evening() {
  const root = useRef<HTMLElement>(null);

  useScene(root, (gsap, el) => {
    const tl = gsap.timeline({ defaults: { ease: "none" } });
    const vertical = window.matchMedia("(max-width: 767px)").matches;
    tl.from(el.querySelector("[data-rail]"), { clipPath: vertical ? "inset(0 0 100% 0)" : "inset(0 100% 0 0)", duration: 4 }, 0);
    el.querySelectorAll("[data-step]").forEach((s, i) => tl.from(s, { opacity: 0.25, duration: 0.5 }, (i / (EVENING.length - 1)) * 3.6));
    tl.from(el.querySelector("[data-tone]"), { opacity: 0, duration: 0.8 }, 3.3);
    return tl;
  });

  return (
    <figure ref={root}>
      <div className="relative">
        <div aria-hidden className="absolute bottom-2 left-[0.45rem] top-2 w-px bg-border md:inset-x-0 md:bottom-auto md:left-0 md:top-[0.45rem] md:h-px md:w-auto" />
        <div aria-hidden data-rail className="absolute bottom-2 left-[0.45rem] top-2 w-px bg-brand md:inset-x-0 md:bottom-auto md:left-0 md:top-[0.45rem] md:h-px md:w-auto" />
        <ol className="relative grid gap-5 md:grid-cols-5 md:gap-3">
          {EVENING.map(([time, what]) => (
            <li key={time} data-step className="flex gap-3 md:block">
              <span aria-hidden className="mt-1 inline-block size-[0.9rem] shrink-0 rounded-full border-2 border-brand bg-background md:mt-0 md:block" />
              <span className="md:mt-3 md:block">
                <time className="block text-sm font-semibold tabular-nums">{time}</time>
                <span className="block text-sm text-muted-foreground">{what}</span>
              </span>
            </li>
          ))}
        </ol>
      </div>

      <div data-tone className="mt-10">
        <p className="text-sm font-medium">How a call&apos;s tone is read</p>
        <div className="relative mt-6 h-8" aria-hidden>
          <div className="flex h-full overflow-hidden rounded-md border">
            {edges.slice(0, -1).map((from, i) => (
              <div key={from} style={{ width: `${((edges[i + 1] - from) / span) * 100}%` }} className={cn(i % 2 ? "bg-(--control)" : "bg-card", i > 0 && "border-l")} />
            ))}
          </div>
          <span style={{ left: pct(TONE.median) }} className="absolute -top-5 -translate-x-1/2 whitespace-nowrap text-[10px] text-muted-foreground">median call</span>
          <span style={{ left: pct(TONE.median) }} className="absolute inset-y-0 w-px bg-foreground/60" />
          <span style={{ left: pct(TONE.sample) }} className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[1px] bg-foreground ring-2 ring-background" />
        </div>
        <p className="mt-5 text-xs text-muted-foreground">
          {TONE.first} below {TONE.cuts[0][0]} · {TONE.cuts.map(([cut, name]) => `${name} from ${cut}`).join(" · ")}. The diamond is an invented call, read as Optimistic; the line is the median call, {TONE.median}.
        </p>
      </div>
      <figcaption className="mt-4 text-xs text-muted-foreground">An example evening with an invented company; times are illustrative, not a schedule.</figcaption>
    </figure>
  );
}
