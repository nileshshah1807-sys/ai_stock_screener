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
 * stage bands. One reveal sweeps left to right over the price and its averages
 * together, and each band shades in as the sweep reaches it. Every band has the
 * same weight and the ink is neutral: no stage is drawn as the good one. The
 * chart is taller than its width suggests on a phone (the svg stretches; its
 * strokes do not) and the band names are HTML, so they stay readable.
 */
export function StageLine() {
  const root = useRef<HTMLElement>(null);

  useScene(root, (gsap, el) => {
    const tl = gsap.timeline({ defaults: { ease: "none" } });
    tl.from(el.querySelector("[data-reveal]"), { attr: { width: 0 }, duration: 4 }, 0);
    el.querySelectorAll("[data-band]").forEach((b, i) => tl.from(b, { opacity: 0, duration: 0.5 }, S.bands[i].from * 4));
    return tl;
  });

  return (
    <figure ref={root}>
      <div className="relative h-64 md:h-[26rem]">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-labelledby="stage-caption" className="absolute inset-0 size-full">
          <defs>
            <clipPath id="stage-reveal">
              <rect data-reveal x="0" y="0" width={W} height={H} />
            </clipPath>
          </defs>
          {S.bands.map((b) => (
            <g key={b.stage} data-band>
              <rect x={b.from * W} y="0" width={(b.to - b.from) * W} height={H} className="fill-foreground" opacity="0.05" />
              {b.from > 0 ? <line x1={b.from * W} x2={b.from * W} y1="0" y2={H} className="stroke-foreground" opacity="0.25" strokeWidth="1" vectorEffect="non-scaling-stroke" /> : null}
            </g>
          ))}
          <g clipPath="url(#stage-reveal)" fill="none">
            {LINES.map((l) => (
              <path key={l.key} d={l.d} className="stroke-muted-foreground" strokeWidth={l.w} strokeDasharray={l.dash} vectorEffect="non-scaling-stroke" />
            ))}
            <path d={path(S.price)} className="stroke-foreground" strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
          </g>
        </svg>
        {S.bands.map((b) => (
          <span
            key={b.stage}
            aria-hidden
            style={{ left: `${((b.from + b.to) / 2) * 100}%` }}
            className="absolute top-2 -translate-x-1/2 text-xs font-medium text-muted-foreground"
          >
            {STAGE_WORD[b.stage as 1 | 2 | 3 | 4]}
          </span>
        ))}
      </div>
      <ul aria-hidden className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
        <li>Price: solid, dark</li>
        <li>50-day: thin line</li>
        <li>150-day: dashes</li>
        <li>200-day: dots</li>
      </ul>
      <figcaption id="stage-caption" className="mt-2 text-xs text-muted-foreground">
        An invented price with its 50, 150 and 200-day averages, passing through four stages: basing, advancing, topping, declining.
      </figcaption>
    </figure>
  );
}
