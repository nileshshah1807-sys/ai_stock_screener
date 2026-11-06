"use client";

import { useRef } from "react";

import { useScene } from "@/components/landing/use-scene";
import { SIEVE_GATES, sieveDots } from "@/lib/landing.mjs";

const GATE_YS = [118, 170, 222];
const WIDTH = 480;
const TOP = 56;
const HEIGHT = 244;
const DOTS = sieveDots({ width: WIDTH, gateYs: GATE_YS, top: 66 });

/**
 * The hero's picture: every stock is a dot, and the three gates let a few
 * through to the ranked row. The markup is the finished picture; scrolling
 * plays it from the top. The dots are an illustration, not data: no dot is a
 * particular stock and none is coloured as good or bad.
 */
export function Sieve() {
  const root = useRef<HTMLElement>(null);

  useScene(root, (gsap, el) => {
    const dots = Array.from(el.querySelectorAll<SVGCircleElement>("[data-dot]"));
    const tl = gsap.timeline({ defaults: { ease: "power2.inOut" } });
    dots.forEach((dot, i) => {
      const d = DOTS[i];
      gsap.set(dot, { attr: { cx: d.startX, cy: d.startY }, opacity: 1 });
      const passes = d.fate === 3;
      const stops = passes ? 3 : d.fate + 1;
      for (let g = 0; g < stops; g++) {
        const stopsHere = !passes && g === stops - 1;
        const share = (g + 1) / (passes ? 4 : stops);
        tl.to(dot, { attr: { cx: d.startX + (d.x - d.startX) * share, cy: stopsHere ? d.y : GATE_YS[g] - 8 }, duration: 1 }, g);
      }
      if (passes) tl.to(dot, { attr: { cx: d.x, cy: d.y }, duration: 1 }, 3);
      tl.fromTo(dot, { opacity: 1 }, { opacity: d.fate === 3 ? 1 : 0.35, duration: 0.3 }, Math.max(d.fate, 0) + 0.8);
    });
    el.querySelectorAll("[data-gate]").forEach((gate, g) => tl.from(gate, { opacity: 0.25, duration: 0.5 }, g));
    el.querySelectorAll("[data-rank]").forEach((r) => tl.from(r, { opacity: 0, duration: 0.5 }, 3.4));
    return tl;
  });

  return (
    <figure ref={root} className="mx-auto w-full max-w-3xl">
      <svg viewBox={`0 ${TOP} ${WIDTH} ${HEIGHT}`} role="img" aria-labelledby="sieve-caption" className="h-auto w-full">
        {SIEVE_GATES.map(([name], g) => (
          <g key={name} data-gate>
            <line x1="0" x2={WIDTH} y1={GATE_YS[g]} y2={GATE_YS[g]} className="stroke-foreground" strokeWidth="1" strokeDasharray="2 5" />
            <text x="2" y={GATE_YS[g] + 14} className="fill-muted-foreground text-[13px] font-medium">{name}</text>
          </g>
        ))}
        {DOTS.map((d) => (
          <circle key={d.id} data-dot cx={d.x} cy={d.y} r={d.fate === 3 ? 5 : 3.2} className="fill-foreground" opacity={d.fate === 3 ? 1 : 0.35} />
        ))}
        {DOTS.filter((d) => d.rank).map((d) => (
          <text key={d.id} data-rank x={d.x} y={d.y + 18} textAnchor="middle" className="fill-muted-foreground text-[12px] tabular-nums">{d.rank}</text>
        ))}
      </svg>
      <figcaption id="sieve-caption" className="mt-2 text-xs text-muted-foreground">
        <ol className="flex flex-wrap gap-x-5 gap-y-1">
          {SIEVE_GATES.map(([name, question], g) => (
            <li key={name}><span className="font-medium text-foreground">{g + 1}. {name}</span> {question}</li>
          ))}
          <li><span className="font-medium text-foreground">Then ranked.</span> Each dot is a stock; an illustration, not data. A solid dot only means it passed the filters.</li>
        </ol>
      </figcaption>
    </figure>
  );
}
