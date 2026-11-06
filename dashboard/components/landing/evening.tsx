"use client";

import { useRef } from "react";

import { useScene } from "@/components/landing/use-scene";
import { EVENING, EVENING_AXIS, TONE, eveningPosition } from "@/lib/landing.mjs";
import { cn } from "@/lib/utils";

const span = TONE.max - TONE.min;
const pct = (v: number) => `${((v - TONE.min) / span) * 100}%`;
const edges: number[] = [TONE.min, ...TONE.cuts.map(([cut]) => Number(cut)), TONE.max];
const HOURS = Array.from({ length: 7 }, (_, i) => 16 + i); // 16:00 .. 22:00
const hourAt = (h: number) => (h * 60 - EVENING_AXIS.from) / (EVENING_AXIS.to - EVENING_AXIS.from);

/**
 * An example evening on a real time axis, 15:30 to 22:00, every event where its
 * time puts it: the filing and its card, 15 minutes apart, sit close. Down a
 * phone the axis runs top to bottom with one line per event; across a desktop
 * the labels alternate above and below the axis so close events do not collide.
 * Beneath it, the scale a call's tone is read on, drawn to the app's real cuts
 * with the median call marked. The call is invented; the ink is neutral.
 */
export function Evening() {
  const root = useRef<HTMLElement>(null);

  useScene(root, (gsap, el) => {
    const tl = gsap.timeline({ defaults: { ease: "none" } });
    const vertical = window.matchMedia("(max-width: 767px)").matches;
    tl.from(el.querySelector("[data-rail]"), { clipPath: vertical ? "inset(0 0 100% 0)" : "inset(0 100% 0 0)", duration: 4 }, 0);
    el.querySelectorAll("[data-dot]").forEach((d, i) => tl.from(d, { scale: 0.4, opacity: 0.3, transformOrigin: "50% 50%", duration: 0.4 }, eveningPosition(EVENING[i][0]) * 4));
    tl.from(el.querySelector("[data-tone]"), { opacity: 0, duration: 0.8 }, 3.3);
    return tl;
  });

  return (
    <figure ref={root}>
      <div className="relative ml-1 h-[26rem] md:ml-0 md:h-44">
        <div aria-hidden className="absolute inset-y-0 left-[0.45rem] w-px bg-border md:inset-x-0 md:inset-y-auto md:left-0 md:top-1/2 md:h-px md:w-auto" />
        <div aria-hidden data-rail className="absolute inset-y-0 left-[0.45rem] w-px bg-brand md:inset-x-0 md:inset-y-auto md:left-0 md:top-1/2 md:h-px md:w-auto" />
        {HOURS.map((h) => (
          <span
            key={h}
            aria-hidden
            style={{ "--at": `${hourAt(h) * 100}%` } as React.CSSProperties}
            className="absolute left-[0.2rem] top-(--at) h-px w-[0.55rem] bg-border md:left-(--at) md:top-1/2 md:h-[0.55rem] md:w-px md:-translate-y-1/2"
          />
        ))}
        <ol>
          {EVENING.map(([time, what], i) => (
            <li
              key={time}
              style={{ "--at": `${eveningPosition(time) * 100}%` } as React.CSSProperties}
              className={cn(
                "absolute left-0 top-(--at) -translate-y-1/2 md:top-1/2 md:left-(--at) md:-translate-x-1/2",
                i === 0 && "md:translate-x-0",
                i === EVENING.length - 1 && "md:-translate-x-full",
              )}
            >
              <span aria-hidden data-dot className="absolute left-0 top-1/2 size-[0.9rem] -translate-y-1/2 rounded-full border-2 border-brand bg-background md:left-1/2 md:-translate-x-1/2" />
              <span
                className={cn(
                  "ml-7 block whitespace-nowrap text-sm leading-5 md:absolute md:ml-0 md:w-40 md:whitespace-normal md:text-center",
                  i % 2 ? "md:top-5" : "md:bottom-5",
                  i === 0 && "md:left-0 md:text-left",
                  i === EVENING.length - 1 && "md:right-0 md:text-right",
                  i !== 0 && i !== EVENING.length - 1 && "md:left-1/2 md:-translate-x-1/2",
                )}
              >
                <time className="font-semibold tabular-nums">{time}</time> <span className="text-muted-foreground">{what}</span>
              </span>
            </li>
          ))}
        </ol>
        <span className="absolute -bottom-5 left-7 text-xs text-muted-foreground md:bottom-0 md:left-auto md:right-0">22:00</span>
      </div>

      <div data-tone className="mt-14">
        <p className="text-sm font-medium">How management sounded on the call</p>
        <div className="relative mt-6 h-8" aria-hidden>
          <div className="flex h-full overflow-hidden rounded-md border">
            {edges.slice(0, -1).map((from, i) => (
              <div key={from} style={{ width: `${((edges[i + 1] - from) / span) * 100}%` }} className={cn(i % 2 ? "bg-(--control)" : "bg-card", i > 0 && "border-l")} />
            ))}
          </div>
          <span style={{ left: pct(TONE.median) }} className="absolute -top-5 -translate-x-1/2 whitespace-nowrap text-xs text-muted-foreground">median call</span>
          <span style={{ left: pct(TONE.median) }} className="absolute inset-y-0 w-px bg-foreground/60" />
          <span style={{ left: pct(TONE.sample) }} className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[1px] bg-foreground ring-2 ring-background" />
        </div>
        <p className="mt-5 text-xs text-muted-foreground">
          {TONE.first} below {TONE.cuts[0][0]} · {TONE.cuts.map(([cut, name]) => `${name} from ${cut}`).join(" · ")}. The diamond is an invented call, read as Optimistic; the line is the median call, {TONE.median}.
        </p>
      </div>
      <figcaption className="mt-4 text-xs text-muted-foreground">An example evening with an invented company; times are illustrative, not a schedule. The axis runs 15:30 to 22:00.</figcaption>
    </figure>
  );
}
