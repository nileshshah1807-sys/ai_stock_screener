"use client";

import { useRef } from "react";

import { useScene } from "@/components/landing/use-scene";
import { STAGE_WORD, stageSeries } from "@/lib/landing.mjs";

const W = 640;
const H = 260;
const PAD = 12;
const S = stageSeries();
const all = [...S.price, ...S.ma50, ...S.ma150, ...S.ma200].filter((v): v is number => v !== null);
const lo = Math.min(...all);
const hi = Math.max(...all);
const x = (i: number) => (i / (S.price.length - 1)) * W;
const y = (v: number) => H - PAD - ((v - lo) / (hi - lo)) * (H - PAD * 2 - 22);
const path = (arr: (number | null)[]) =>
  arr.map((v, i) => (v === null ? "" : `${arr.slice(0, i).some((p) => p !== null) ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`)).join("");

const LINES = [
  { key: "ma200", label: "200-day average", d: path(S.ma200), dash: "1 5", w: 1.6 },
  { key: "ma150", label: "150-day average", d: path(S.ma150), dash: "6 4", w: 1.4 },
  { key: "ma50", label: "50-day average", d: path(S.ma50), dash: undefined, w: 1.2 },
];

/**
 * A made-up price history with its 50, 150 and 200-day averages, in the four
 * stage bands. The bands shade in as the price line reaches them. The history
 * is invented and neutral ink throughout: no stage is coloured as the good one.
 */
export function StageLine() {
  const root = useRef<HTMLElement>(null);

  useScene(root, (gsap, el) => {
    const tl = gsap.timeline({ defaults: { ease: "none" } });
    const bands = Array.from(el.querySelectorAll("[data-band]"));
    tl.from(el.querySelector("[data-price]"), { attr: { "stroke-dashoffset": 1 }, duration: 4 }, 0);
    el.querySelectorAll("[data-ma]").forEach((m, i) => tl.from(m, { opacity: 0, duration: 1 }, 0.4 + i * 0.3));
    bands.forEach((b, i) => tl.from(b, { opacity: 0, duration: 0.6 }, S.bands[i].from * 4));
    return tl;
  });

  return (
    <figure ref={root}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="stage-caption" className="h-auto w-full">
        {S.bands.map((b, i) => (
          <g key={b.stage} data-band>
            <rect x={b.from * W} y="0" width={(b.to - b.from) * W} height={H} className="fill-foreground" opacity={i % 2 ? 0.07 : 0.03} />
            <text x={(b.from + b.to) * W / 2} y="16" textAnchor="middle" className="fill-muted-foreground text-[11px] font-medium">{STAGE_WORD[b.stage as 1 | 2 | 3 | 4]}</text>
          </g>
        ))}
        {LINES.map((l) => (
          <path key={l.key} data-ma d={l.d} fill="none" className="stroke-muted-foreground" strokeWidth={l.w} strokeDasharray={l.dash} />
        ))}
        <path data-price d={path(S.price)} pathLength={1} strokeDasharray={1} strokeDashoffset={0} fill="none" className="stroke-foreground" strokeWidth="2" strokeLinejoin="round" />
      </svg>
      <figcaption id="stage-caption" className="mt-2 text-xs text-muted-foreground">
        An invented price history, solid, against its 50-day (line), 150-day (dashes) and 200-day (dots) averages. It rests under flat averages (basing), climbs above them stacked in order (advancing), slips under the 150-day while the long averages hold (topping), then falls under a falling 200-day (declining).
      </figcaption>
    </figure>
  );
}
