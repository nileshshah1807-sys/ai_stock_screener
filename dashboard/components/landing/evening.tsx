"use client";

import { Bell } from "lucide-react";
import { useRef } from "react";

import { useScene } from "@/components/landing/use-scene";
import { EVENING, EVENING_AXIS, TONE, eveningPosition, labelShifts, toneName } from "@/lib/landing.mjs";
import { cn } from "@/lib/utils";

const span = TONE.max - TONE.min;
const pct = (v: number) => `${((v - TONE.min) / span) * 100}%`;
const edges: number[] = [TONE.min, ...TONE.cuts.map(([cut]) => Number(cut)), TONE.max];
const callTone = toneName(TONE.sample);
const medianTone = toneName(TONE.median);
const HOURS = Array.from({ length: 7 }, (_, i) => 16 + i); // 16:00 .. 22:00
/** Phone labels keep a minimum gap down the axis; a dot stays at its time, a label may sit a little below it. */
const PHONE_AXIS_REM = 30;
const shifts = labelShifts(EVENING.map(([t]) => eveningPosition(t) * PHONE_AXIS_REM), 1.75);
const hourAt = (h: number) => (h * 60 - EVENING_AXIS.from) / (EVENING_AXIS.to - EVENING_AXIS.from);

/** What the app shows at 18:25: the results card, as a miniature. Invented company and figures. */
function MiniCard() {
  return (
    <span className="panel block p-2.5 text-left text-xs leading-4">
      <span className="block font-semibold">Aarav Industries</span>
      <span className="block text-muted-foreground">Invented · Sep quarter</span>
      <span className="mt-1.5 flex justify-between gap-4 tabular-nums"><span className="text-muted-foreground">Revenue</span>₹4,120 Cr</span>
      <span className="flex justify-between gap-4 tabular-nums"><span className="text-muted-foreground">Profit</span>₹512 Cr</span>
    </span>
  );
}

/** What the app shows at 21:10: one row of the bell. */
function MiniBell() {
  return (
    <span className="panel flex items-center gap-2 p-2.5 text-left text-xs leading-4">
      <Bell className="size-4 shrink-0 text-brand" aria-hidden />
      <span><span className="block font-semibold">Aarav Industries</span><span className="block text-muted-foreground">Call tone is in</span></span>
    </span>
  );
}

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
    return tl;
  });

  return (
    <figure ref={root}>
      <div className="relative ml-1 h-[30rem] md:ml-0 md:h-64">
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
              style={{ "--at": `${eveningPosition(time) * 100}%`, "--shift": `${shifts[i]}rem` } as React.CSSProperties}
              className={cn(
                "absolute left-0 top-(--at) -translate-y-1/2 md:top-1/2 md:left-(--at) md:-translate-x-1/2",
                i === 0 && "md:translate-x-0",
                i === EVENING.length - 1 && "md:-translate-x-full",
              )}
            >
              <span aria-hidden data-dot className="absolute left-0 top-1/2 size-[0.9rem] -translate-y-1/2 rounded-full border-2 border-brand bg-background md:left-1/2 md:-translate-x-1/2" />
              <span
                className={cn(
                  "ml-7 block whitespace-nowrap max-md:relative max-md:top-(--shift) text-sm leading-5 md:absolute md:ml-0 md:w-40 md:whitespace-normal md:text-center",
                  i % 2 ? "md:top-5" : "md:bottom-5",
                  i === 0 && "md:left-0 md:text-left",
                  i === EVENING.length - 1 && "md:right-0 md:text-right",
                  i !== 0 && i !== EVENING.length - 1 && "md:left-1/2 md:-translate-x-1/2",
                )}
              >
                <time className="font-semibold tabular-nums">{time}</time> <span className="text-muted-foreground">{what}</span>
                {i === 2 ? <span className="mt-2 hidden md:block"><MiniCard /></span> : null}
                {i === 4 ? <span className="mt-2 hidden md:block"><MiniBell /></span> : null}
              </span>
            </li>
          ))}
        </ol>
        <span className="absolute -bottom-5 left-7 text-xs text-muted-foreground md:bottom-auto md:left-auto md:right-0 md:top-1/2 md:mt-3">22:00</span>
      </div>

      <div className="mt-10 grid grid-cols-2 gap-2 md:hidden">
        <MiniCard />
        <MiniBell />
      </div>

      <div data-tone className="mt-14 md:mt-20">
        <h3 className="text-base font-semibold">How management sounded on the call</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          This call reads <strong className="font-semibold text-foreground">{callTone}</strong>; the median call reads {medianTone}.
          <span className="sr-only"> {TONE.first} below {TONE.cuts[0][0]}; {TONE.cuts.map(([cut, name]) => `${name} from ${cut}`).join("; ")}.</span>
        </p>
        <div className="relative mb-12 mt-14" aria-hidden>
          <div className="flex h-12 overflow-hidden rounded-md border">
            {edges.slice(0, -1).map((from, i) => {
              const name = i === 0 ? TONE.first : TONE.cuts[i - 1][1];
              const here = name === callTone;
              return (
                <div key={from} style={{ width: `${((edges[i + 1] - from) / span) * 100}%` }} className={cn("flex items-center justify-center whitespace-nowrap text-xs font-medium text-muted-foreground", i > 0 && "border-l", here && "bg-brand-soft font-semibold text-foreground shadow-[inset_0_2px_0_var(--brand)]")}>
                  {name}
                </div>
              );
            })}
          </div>
          <span style={{ left: pct(TONE.sample) }} className="absolute bottom-full mb-1 flex -translate-x-1/2 flex-col items-center gap-0.5 whitespace-nowrap text-xs font-semibold text-brand">
            This call
            <span className="h-1.5 w-2.5 bg-brand [clip-path:polygon(0_0,100%_0,50%_100%)]" />
          </span>
          <span style={{ left: pct(TONE.median) }} className="absolute top-full mt-1 flex -translate-x-1/2 flex-col items-center gap-0.5 whitespace-nowrap text-xs text-muted-foreground">
            <span className="h-1.5 w-2.5 bg-current [clip-path:polygon(50%_0,0_100%,100%_100%)]" />
            Median call
          </span>
        </div>
      </div>
      <figcaption className="mt-2 text-xs text-muted-foreground">An example evening, invented company, illustrative times.</figcaption>
    </figure>
  );
}
