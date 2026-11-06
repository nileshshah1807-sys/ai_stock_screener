"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { Bell, Check, ChartColumn, ChartPie, Globe, Mic, SlidersHorizontal, type LucideIcon } from "lucide-react";

import { PERIOD_LABEL, planTitle, priceLabel } from "@/lib/billing.mjs";
import type { Plan } from "@/lib/plans";
import { cn } from "@/lib/utils";

gsap.registerPlugin(ScrollTrigger);

/** What a subscription covers. No price, rating or return is stated here. */
const INCLUDED: { icon: LucideIcon; text: string }[] = [
  { icon: Globe, text: "NSE and US stocks under one subscription" },
  { icon: SlidersHorizontal, text: "A screener with filters and saved views, and a page for every stock" },
  { icon: ChartColumn, text: "Quarterly results as companies file them, with a results analysis" },
  { icon: Mic, text: "Earnings calls: upcoming dates and what management said" },
  { icon: ChartPie, text: "Shareholding patterns and company documents for Indian stocks" },
  { icon: Bell, text: "Watchlists and a bell for new results and calls" },
];

/** One plan as the server worked it out: every sentence and button is made there, so no date or price is formatted twice. */
export type PlanPanel = {
  plan: Plan;
  isCurrent: boolean;
  badge: "value" | null;
  /** The early-bird sentence, only while the offer is open. */
  note: string | null;
  facts: { label: string; value: string }[];
  action: React.ReactNode;
};

const HOVER_FINE = "(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)";
const MOTION_OK = "(prefers-reduced-motion: no-preference)";

const shownPaise = (plan: Plan) => plan.offer?.amount_paise ?? plan.amount_paise;
const periodName = (plan: Plan) => (plan.period === "yearly" ? "Yearly" : plan.period === "monthly" ? "Monthly" : "Plan");

/**
 * The plans as a toggle and one card, and the feature comparison under it.
 *
 * Motion follows components/motion.tsx's rules: content is in the HTML and
 * gsap.from() sets a start state at runtime; reduced motion is a real branch
 * (gsap.matchMedia) that runs nothing and leaves the page static; no layout
 * property moves. Every plan's panel is always rendered, stacked in one grid
 * cell, so the card is as tall as its tallest plan and a toggle never moves
 * what is below it.
 */
export function PricingPlans({
  panels,
  initialId,
  note,
  embedded = false,
}: {
  panels: PlanPanel[];
  initialId: string;
  note?: React.ReactNode;
  /** Inside another page (the landing's pricing section): the arrival waits to be scrolled to, and the page-wide ruled backdrop is left out. */
  embedded?: boolean;
}) {
  const [selectedId, setSelectedId] = useState(initialId);
  const root = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const table = useRef<HTMLTableElement>(null);
  const selected = Math.max(0, panels.findIndex((p) => p.plan.id === selectedId));

  // Before paint, so the hidden start state of the arrival never shows after hydration.
  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      const mm = gsap.matchMedia();

      mm.add(MOTION_OK, () => {
        // Arrival: the toggle and card rise in; the comparison waits to be scrolled to.
        gsap.from(root.current?.querySelectorAll("[data-arrive]") ?? [], {
          opacity: 0,
          y: 16,
          duration: 0.6,
          ease: "expo.out",
          stagger: 0.09,
          clearProps: "transform,opacity",
          scrollTrigger: embedded ? { trigger: root.current, start: "top 85%", once: true } : undefined,
        });
        const rows = table.current?.querySelectorAll("tbody tr");
        if (rows?.length) {
          const trigger = { trigger: table.current, start: "top 88%", once: true };
          gsap.from(rows, { opacity: 0, y: 12, duration: 0.45, ease: "expo.out", stagger: 0.06, clearProps: "transform,opacity", scrollTrigger: trigger });
          // The marks pop in behind their rows, as if ticked off.
          gsap.from(table.current?.querySelectorAll("[data-tick]") ?? [], {
            scale: 0,
            duration: 0.4,
            ease: "back.out(2.4)",
            stagger: 0.035,
            delay: 0.15,
            clearProps: "transform",
            scrollTrigger: trigger,
          });
        }
      });

      // Tilt follows a mouse, never a finger: a card tipping under a scrolling thumb is noise.
      mm.add(HOVER_FINE, () => {
        const el = card.current;
        if (!el) return;
        const rx = gsap.quickTo(el, "rotationX", { duration: 0.5, ease: "power3.out" });
        const ry = gsap.quickTo(el, "rotationY", { duration: 0.5, ease: "power3.out" });
        const move = (event: PointerEvent) => {
          const r = el.getBoundingClientRect();
          const x = (event.clientX - r.left) / r.width;
          const y = (event.clientY - r.top) / r.height;
          ry((x - 0.5) * 6);
          rx((0.5 - y) * 6);
        };
        const leave = () => {
          rx(0);
          ry(0);
        };
        el.addEventListener("pointermove", move);
        el.addEventListener("pointerleave", leave);
        return () => {
          el.removeEventListener("pointermove", move);
          el.removeEventListener("pointerleave", leave);
          gsap.set(el, { clearProps: "rotationX,rotationY,transform" });
        };
      });
    }, root);
    return () => ctx.revert();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `embedded` is fixed per page; the effect runs once
  }, []);

  return (
    <div ref={root} className="[--brand-soft:color-mix(in_oklab,var(--rating-strong-buy)_12%,var(--card))] [--brand:var(--rating-strong-buy)]">
      {/* The backdrop is decoration: it carries no content and is out of the reading order. */}
      <div
        aria-hidden
        hidden={embedded}
        className="pointer-events-none fixed inset-0 -z-10 [background-image:linear-gradient(to_bottom,transparent_calc(100%_-_1px),var(--border)_0)] [background-size:100%_2.5rem] [mask-image:linear-gradient(to_bottom,#000_40%,transparent)]"
      />

      {panels.length > 1 ? (
        <div data-arrive>
          <PeriodToggle panels={panels} selected={selected} onSelect={setSelectedId} />
        </div>
      ) : null}

      <div data-arrive className="mt-5 [perspective:1100px]">
        <div
          ref={card}
          className={cn(
            "panel group/card relative overflow-hidden p-6 [transform-style:preserve-3d] sm:p-8",
            // The recommended plan takes the accent on its edge; any other stays a plain panel.
            panels[selected]?.badge === "value" && "border-brand/50",
          )}
        >
          <div className="relative grid">
            {panels.map((panel, index) => (
              <Panel key={panel.plan.id} panel={panel} active={index === selected} />
            ))}
          </div>
        </div>
      </div>

      {note ? <div data-arrive className="mt-3">{note}</div> : null}

      <section aria-labelledby="included-heading" className="mt-10">
        <h2 id="included-heading" className="text-sm font-semibold">
          Both plans include
        </h2>
        <div className="panel mt-3 overflow-hidden">
          <table ref={table} className="w-full table-fixed border-collapse text-sm">
            <thead>
              <tr className="border-b">
                <th scope="col" className="sr-only">
                  Included
                </th>
                {panels.map((panel, index) => (
                  <th key={panel.plan.id} scope="col" className={cn("w-[4.5rem] px-1 py-2 sm:w-32", index === selected && "bg-brand-soft/60")}>
                    <button
                      type="button"
                      aria-pressed={index === selected}
                      onClick={() => setSelectedId(panel.plan.id)}
                      className={cn(
                        "w-full rounded-md px-2 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        index === selected ? "text-brand" : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {periodName(panel.plan)}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {INCLUDED.map(({ icon: Icon, text }) => (
                <tr key={text} className="group/row border-b transition-colors last:border-b-0 hover:bg-(--control)/60">
                  <th scope="row" className="py-3 pr-2 pl-4 text-left font-normal sm:pl-5">
                    <span className="flex items-start gap-3">
                      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground transition-colors duration-200 group-hover/row:text-brand" aria-hidden />
                      <span>{text}</span>
                    </span>
                  </th>
                  {panels.map((panel, index) => (
                    <td key={panel.plan.id} className={cn("px-1 text-center align-middle", index === selected && "bg-brand-soft/60")}>
                      <span
                        data-tick
                        className="mx-auto flex size-6 items-center justify-center rounded-full bg-positive/10 text-positive transition-[transform,background-color,color] duration-200 group-hover/row:scale-110 group-hover/row:bg-positive group-hover/row:text-background"
                      >
                        <Check className="size-3.5" strokeWidth={2.5} aria-hidden />
                        <span className="sr-only">Included</span>
                      </span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

/** Monthly / Yearly, with an indicator that slides between the two. */
function PeriodToggle({ panels, selected, onSelect }: { panels: PlanPanel[]; selected: number; onSelect: (id: string) => void }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const n = panels.length;

  // Arrow keys move the choice, as a radio group's do.
  const onKeyDown = (event: React.KeyboardEvent) => {
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = (selected + step + n) % n;
    onSelect(panels[next].plan.id);
    refs.current[next]?.focus();
  };

  return (
    <div
      role="radiogroup"
      aria-label="Billing period"
      onKeyDown={onKeyDown}
      className="relative inline-grid rounded-full bg-(--control) p-1"
      style={{ gridTemplateColumns: `repeat(${n}, 1fr)` }}
    >
      <span
        aria-hidden
        className="absolute inset-y-1 left-1 rounded-full bg-card shadow-sm ring-1 ring-border transition-transform duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]"
        style={{ width: `calc((100% - 0.5rem) / ${n})`, transform: `translateX(${selected * 100}%)` }}
      />
      {panels.map((panel, index) => {
        const on = index === selected;
        const save = panel.badge === "value" ? panel.facts.find((f) => f.label === "Compared with monthly")?.value : null;
        return (
          <button
            key={panel.plan.id}
            ref={(el) => {
              refs.current[index] = el;
            }}
            type="button"
            role="radio"
            aria-checked={on}
            tabIndex={on ? 0 : -1}
            onClick={() => onSelect(panel.plan.id)}
            className={cn(
              "relative z-10 flex min-h-9 items-center justify-center gap-2 rounded-full px-5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              on ? "text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {periodName(panel.plan)}
            {save && save !== "-" ? <span className="rounded-full bg-positive/10 px-1.5 py-0.5 text-micro font-medium text-positive">{save}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

/** One plan's card body. All are mounted; only the active one is seen, read or focusable. */
function Panel({ panel, active }: { panel: PlanPanel; active: boolean }) {
  const { plan, isCurrent, badge, note, facts, action } = panel;
  const period = PERIOD_LABEL[plan.period] ?? plan.period;
  // A plan with an offer opens on its regular price and falls to the offer price: that is the moment.
  const from = plan.offer ? plan.amount_paise : shownPaise(plan);

  return (
    <div
      inert={!active}
      aria-hidden={!active}
      className={cn(
        "col-start-1 row-start-1 grid gap-6 transition-[opacity,transform] duration-300 ease-out sm:grid-cols-[1.15fr_1fr] sm:gap-10",
        active ? "opacity-100" : "translate-y-1.5 opacity-0",
      )}
    >
      <div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <h2 className="text-lead font-semibold">{planTitle(plan)}</h2>
          {isCurrent ? (
            <span className="rounded-md bg-primary px-2 py-0.5 text-xs font-medium text-primary-foreground">Current plan</span>
          ) : badge === "value" ? (
            <span className="rounded-md bg-positive/10 px-2 py-0.5 text-xs font-medium text-positive">Best value</span>
          ) : null}
        </div>

        <p className="mt-4 flex flex-wrap items-baseline gap-x-2 tabular-nums">
          <PriceFigure to={shownPaise(plan)} from={from} active={active} className="text-display" />
          <span className="text-sm text-muted-foreground">per {period}</span>
          {plan.offer ? <StruckPrice paise={plan.amount_paise} active={active} /> : null}
        </p>

        {plan.offer && note ? (
          <div className="mt-4 rounded-row bg-brand-soft px-3.5 py-3 text-xs leading-relaxed tabular-nums">
            <Countdown endsAt={plan.offer.ends_at} />
            <p>{note}</p>
          </div>
        ) : null}
      </div>

      <div className="flex flex-col">
        <dl className="space-y-2.5 text-sm">
          {facts.map((fact) => (
            <div key={fact.label} className="flex justify-between gap-4">
              <dt className="text-muted-foreground">{fact.label}</dt>
              <dd className="text-right font-medium tabular-nums">{fact.value}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-auto pt-6">{action}</div>
      </div>
    </div>
  );
}

/**
 * A price that counts from one value to another when its plan comes into view.
 * The HTML holds the final price, and a screen reader is given it too, so the
 * count is only ever a picture of the figure, never the figure.
 */
function PriceFigure({ to, from, active, className }: { to: number; from: number; active: boolean; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const mounted = useRef(false);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const settle = () => {
      el.textContent = priceLabel(to);
    };
    const mm = gsap.matchMedia();
    mm.add(MOTION_OK, () => {
      if (!active || from === to) return settle();
      const counter = { v: from };
      el.textContent = priceLabel(from);
      const tween = gsap.to(counter, {
        v: to,
        duration: 0.9,
        // The first arrival waits a beat for the card to settle.
        delay: mounted.current ? 0 : 0.55,
        ease: "expo.out",
        onUpdate: () => {
          el.textContent = priceLabel(Math.round(counter.v / 100) * 100);
        },
        onComplete: settle,
      });
      return () => {
        tween.kill();
        settle();
      };
    });
    mm.add("(prefers-reduced-motion: reduce)", settle);
    mounted.current = true;
    return () => mm.revert();
  }, [to, from, active]);

  return (
    <>
      <span ref={ref} aria-hidden className={cn("font-semibold", className)}>
        {priceLabel(to)}
      </span>
      <span className="sr-only">{priceLabel(to)}</span>
    </>
  );
}

/** The regular price, struck through by a line that draws across it. */
function StruckPrice({ paise, active }: { paise: number; active: boolean }) {
  const line = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const el = line.current;
    if (!el || !active) return;
    const mm = gsap.matchMedia();
    mm.add(MOTION_OK, () => {
      const tween = gsap.from(el, { scaleX: 0, duration: 0.5, delay: 0.3, ease: "power3.out", transformOrigin: "left center", clearProps: "transform" });
      return () => {
        tween.kill();
      };
    });
    return () => mm.revert();
  }, [active]);

  return (
    <s className="relative text-sm text-muted-foreground no-underline" aria-label={`regular price ${priceLabel(paise)}`}>
      {priceLabel(paise)}
      <span ref={line} aria-hidden className="absolute inset-x-0 top-1/2 h-px bg-current" />
    </s>
  );
}

/**
 * Time left on the early-bird price, from the offer's end date. It renders
 * nothing on the server (the time there is not the reader's), nothing without
 * a date, and nothing once the date has passed: the sentence beside it still
 * states the date, so the countdown is only ever extra.
 */
function Countdown({ endsAt }: { endsAt: string | null }) {
  const end = endsAt ? new Date(endsAt).getTime() : NaN;
  const [left, setLeft] = useState<number | null>(null);

  useEffect(() => {
    if (Number.isNaN(end)) return;
    const tick = () => setLeft(Math.max(0, end - Date.now()));
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [end]);

  if (left === null || left <= 0) return null;
  const s = Math.floor(left / 1000);
  const parts = [
    ["d", Math.floor(s / 86400)],
    ["h", Math.floor((s % 86400) / 3600)],
    ["m", Math.floor((s % 3600) / 60)],
    ["s", s % 60],
  ] as const;
  const words = parts.map(([u, v]) => `${v}${u}`).join(" ");

  return (
    <div role="timer" aria-label={`Offer ends in ${words}`} className="mb-2.5 flex items-center gap-1.5">
      <span className="mr-1 text-xs font-medium text-brand">Ends in</span>
      {parts.map(([unit, value]) => (
        <span key={unit} aria-hidden className="flex min-w-9 items-baseline justify-center gap-0.5 rounded-md bg-card px-1.5 py-1 shadow-sm ring-1 ring-border">
          <span className="text-sm font-semibold tabular-nums text-foreground">{String(value).padStart(2, "0")}</span>
          <span className="text-micro text-muted-foreground">{unit}</span>
        </span>
      ))}
    </div>
  );
}
