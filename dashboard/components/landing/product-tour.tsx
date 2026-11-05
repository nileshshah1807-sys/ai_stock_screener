"use client";

import { useId, useLayoutEffect, useRef, useState } from "react";

import { CountUp } from "@/components/motion";
import { cn } from "@/lib/utils";

/*
 * Faithful mocks of four pages of the app. Companies are invented and the
 * figures are placeholders; each panel carries a caption saying so. No rating,
 * return or recommendation appears in any of them.
 */

const TABS = [
  { id: "results", label: "Results", blurb: "A quarter's numbers beside the year-ago quarter, as the company filed them, the moment they are stored." },
  { id: "concalls", label: "Earnings calls", blurb: "What management said, summarised, with the statements that moved the read most quoted back." },
  { id: "market", label: "Market breadth", blurb: "How many stocks sit above their long averages and how many are in Stage 2, redrawn after each close." },
  { id: "indices", label: "Indices", blurb: "Every index's constituents in the same grid you screen with." },
] as const;

type TabId = (typeof TABS)[number]["id"];

export function ProductTour() {
  const [tab, setTab] = useState<TabId>("results");
  const base = useId();
  const active = TABS.find((t) => t.id === tab)!;
  const mark = useRef<HTMLSpanElement>(null);

  // The underline slides to the chosen tab; it is measured, so it follows the
  // real label widths and the tab strip's own scroll on a narrow screen.
  useLayoutEffect(() => {
    const button = document.getElementById(`${base}-${tab}`);
    if (!button || !mark.current) return;
    mark.current.style.width = `${button.offsetWidth}px`;
    mark.current.style.transform = `translateX(${button.offsetLeft}px)`;
  }, [tab, base]);

  const move = (event: React.KeyboardEvent, index: number) => {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = TABS[(index + step + TABS.length) % TABS.length];
    setTab(next.id);
    document.getElementById(`${base}-${next.id}`)?.focus();
  };

  return (
    <div>
      <div role="tablist" aria-label="Product pages" className="landing-tabbar flex gap-1 overflow-x-auto border-b">
        <span ref={mark} aria-hidden className="landing-tabmark" />
        {TABS.map((t, i) => (
          <button
            key={t.id}
            id={`${base}-${t.id}`}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            aria-controls={`${base}-panel`}
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => setTab(t.id)}
            onKeyDown={(e) => move(e, i)}
            className={cn(
              "shrink-0 px-4 py-2.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              tab === t.id ? "text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div id={`${base}-panel`} role="tabpanel" aria-labelledby={`${base}-${tab}`} className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)] lg:items-start">
        <p className="max-w-[44ch] text-lead text-muted-foreground">{active.blurb}</p>
        <div key={tab} className="motion-safe:animate-rise">
          {tab === "results" && <ResultsMock />}
          {tab === "concalls" && <CallsMock />}
          {tab === "market" && <BreadthMock />}
          {tab === "indices" && <IndicesMock />}
          <p className="mt-2 text-xs text-muted-foreground">Sample page with invented companies and placeholder figures, not live data.</p>
        </div>
      </div>
    </div>
  );
}

const RESULT_ROWS = [
  ["Revenue", "₹1,284 Cr", "₹1,102 Cr", "+16.5%"],
  ["Operating profit", "₹241 Cr", "₹198 Cr", "+21.7%"],
  ["Net profit", "₹163 Cr", "₹140 Cr", "+16.4%"],
  ["EPS (₹)", "12.4", "10.7", "+15.9%"],
];

function ResultsMock() {
  return (
    <div className="panel p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-semibold">Aarav Industries <span className="font-normal text-muted-foreground">AARAV</span></p>
        <p className="text-xs text-muted-foreground">September 2026 quarter · Consolidated</p>
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[20rem] text-sm tabular-nums">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th scope="col" className="py-2 font-medium">&nbsp;</th>
              <th scope="col" className="py-2 text-right font-medium">This quarter</th>
              <th scope="col" className="py-2 text-right font-medium">Year ago</th>
              <th scope="col" className="py-2 text-right font-medium">Change</th>
            </tr>
          </thead>
          <tbody>
            {RESULT_ROWS.map(([name, now, ago, change]) => (
              <tr key={name} className="border-b last:border-0">
                <th scope="row" className="py-2 text-left font-normal">{name}</th>
                <td className="py-2 text-right">{now}</td>
                <td className="py-2 text-right text-muted-foreground">{ago}</td>
                <td className="py-2 text-right text-positive">{change}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const CALLS = [
  ["Navdeep Chemicals", "Optimistic", "We expect volumes in the specialty range to keep growing through the second half as the new line ramps up."],
  ["Kesari Foods", "Neutral", "Input costs have eased, but we are holding prices while the festive quarter plays out."],
  ["Tarang Power", "Cautious", "Capacity additions are on schedule; the timing of one project depends on grid approvals we do not control."],
];

function CallsMock() {
  return (
    <ul className="panel divide-y">
      {CALLS.map(([name, stance, quote]) => (
        <li key={name} className="p-4">
          <p className="flex flex-wrap items-center justify-between gap-2 text-sm font-semibold">
            {name}
            <span className="rounded bg-(--control) px-2 py-0.5 text-xs font-medium text-muted-foreground">Management tone: {stance}</span>
          </p>
          <blockquote className="mt-2 text-sm leading-relaxed text-muted-foreground">“{quote}”</blockquote>
        </li>
      ))}
    </ul>
  );
}

const BREADTH = [38, 41, 40, 46, 52, 49, 55, 61, 58, 64, 70, 67, 72, 69, 75];

function BreadthMock() {
  const w = 320;
  const h = 120;
  const points = BREADTH.map((v, i) => `${((i / (BREADTH.length - 1)) * w).toFixed(1)},${(h - (v / 100) * h).toFixed(1)}`);
  return (
    <div className="panel p-4">
      <div className="flex flex-wrap gap-x-8 gap-y-2">
        <div>
          <p className="text-xs text-muted-foreground">Above 200-day average</p>
          <p className="text-title font-semibold tabular-nums"><CountUp value={62} />%</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Stocks in Stage 2</p>
          <p className="text-title font-semibold tabular-nums"><CountUp value={412} /></p>
        </div>
      </div>
      <svg viewBox={`0 0 ${w} ${h + 4}`} className="mt-3 h-32 w-full" role="img" aria-label="Sample line chart of the share of stocks above their 200-day average, rising over fifteen sessions">
        {[25, 50, 75].map((p) => (
          <line key={p} x1="0" x2={w} y1={h - (p / 100) * h} y2={h - (p / 100) * h} stroke="var(--border)" strokeWidth="1" />
        ))}
        <polyline
          points={points.join(" ")}
          fill="none"
          stroke="var(--chart-line)"
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
          pathLength={1}
          className="landing-draw"
        />
      </svg>
    </div>
  );
}

const INDICES = [
  ["Large-cap 50", "50", "+0.62%"],
  ["Mid-cap 100", "100", "+1.04%"],
  ["Bank 12", "12", "−0.38%"],
  ["IT 20", "20", "+0.21%"],
];

function IndicesMock() {
  return (
    <div className="panel overflow-x-auto">
      <table className="w-full min-w-[18rem] text-sm tabular-nums">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th scope="col" className="px-4 py-2 font-medium">Index</th>
            <th scope="col" className="px-4 py-2 text-right font-medium">Constituents</th>
            <th scope="col" className="px-4 py-2 text-right font-medium">1D</th>
          </tr>
        </thead>
        <tbody>
          {INDICES.map(([name, count, day]) => (
            <tr key={name} className="border-b last:border-0">
              <th scope="row" className="px-4 py-2.5 text-left font-medium">{name}</th>
              <td className="px-4 py-2.5 text-right">{count}</td>
              <td className={cn("px-4 py-2.5 text-right", day.startsWith("+") ? "text-positive" : "text-negative")}>{day}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
