"use client";

import { useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import gsap from "gsap";

import { cn } from "@/lib/utils";

/**
 * GSAP motion primitives.
 *
 * Three rules hold across everything in this file, and they are what keep an
 * animated data tool usable rather than merely lively:
 *
 * 1. Content is never hidden by CSS. Every effect uses gsap.from(), which sets
 *    the start state at runtime. If the bundle fails, JS is disabled, or the
 *    element is server-rendered and never hydrates, the content is simply
 *    there -- an `opacity: 0` in a stylesheet waiting for JS to undo it is a
 *    blank page for anyone whose JS never arrives.
 *
 * 2. Reduced motion is honoured through gsap.matchMedia(), which is a real
 *    branch rather than a shortened duration: the reduced path sets the final
 *    state immediately and runs nothing.
 *
 * 3. Nothing animates a layout property. Transform and opacity only, so no
 *    effect here can trigger reflow or shift a neighbour mid-flight.
 */

/** Shared easing. Overshoots slightly on settle -- this is the "bounce". */
const EASE_BOUNCE = "back.out(1.6)";
const EASE_OUT = "power3.out";

const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";

/*
 * matchMedia is an external store, so it is read with useSyncExternalStore
 * rather than an effect that calls setState. The effect version renders once
 * with the wrong answer and then immediately re-renders with the right one --
 * which for CountUp means the count can start before the component learns the
 * user asked for no motion. The server snapshot returns false because the
 * preference is not knowable during SSR; the client corrects it on hydration
 * without a second render pass.
 */
function subscribe(onChange: () => void) {
  const mq = window.matchMedia(REDUCED_QUERY);
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}

function usePrefersReducedMotion() {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(REDUCED_QUERY).matches,
    () => false,
  );
}

/**
 * Reveals its children on mount, optionally staggered.
 *
 * `selector` targets descendants to stagger individually; without it the
 * container itself animates as one object. Staggering is capped by
 * `maxStagger` so a long list cannot turn a reveal into a progress bar -- at
 * 100 grid rows an uncapped 40ms step would run for four seconds.
 */
export function Reveal({
  children,
  className,
  selector,
  stagger = 0.04,
  maxStagger = 0.36,
  y = 14,
  delay = 0,
  bounce = false,
}: {
  children: React.ReactNode;
  className?: string;
  selector?: string;
  stagger?: number;
  maxStagger?: number;
  y?: number;
  delay?: number;
  bounce?: boolean;
}) {
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = root.current;
    if (!el) return;

    const ctx = gsap.context(() => {
      const mm = gsap.matchMedia();

      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const targets = selector
          ? Array.from(el.querySelectorAll(selector))
          : [el];
        if (!targets.length) return;

        const each = Math.min(stagger, maxStagger / Math.max(1, targets.length));

        gsap.from(targets, {
          opacity: 0,
          y,
          duration: bounce ? 0.55 : 0.4,
          ease: bounce ? EASE_BOUNCE : EASE_OUT,
          stagger: each,
          delay,
          clearProps: "transform,opacity",
        });
      });

      // Reduced motion: no tween at all. gsap.from() never ran, so the element
      // is already in its natural state -- nothing to reset.
      mm.add("(prefers-reduced-motion: reduce)", () => {});
    }, el);

    return () => ctx.revert();
  }, [selector, stagger, maxStagger, y, delay, bounce]);

  return (
    <div ref={root} className={className}>
      {children}
    </div>
  );
}

/**
 * Counts a figure up to its value.
 *
 * Renders the final formatted string on the server and in the initial HTML,
 * then re-animates from zero on the client. A reader who never gets JS, or who
 * asks for reduced motion, sees the correct number immediately; the count is
 * decoration layered on top, never the source of truth.
 *
 * Formatting is done here from a `locale` string rather than by a `format`
 * callback passed in. Every caller is a Server Component, and a function is
 * not serializable across that boundary -- passing one throws "Functions
 * cannot be passed directly to Client Components" at render time. A locale
 * tag is a plain string and crosses the boundary fine.
 *
 * The formatter is built once per locale instead of per frame; at 60fps for
 * over a second, constructing Intl.NumberFormat inside onUpdate would be ~70
 * throwaway allocations per figure.
 */
export function CountUp({
  value,
  locale = "en-IN",
  duration = 1.1,
  className,
}: {
  value: number;
  locale?: string;
  duration?: number;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const reduced = usePrefersReducedMotion();
  const nf = useMemo(
    () => new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }),
    [locale],
  );

  useEffect(() => {
    const el = ref.current;
    if (!el || reduced) return;

    const counter = { n: 0 };
    const tween = gsap.to(counter, {
      n: value,
      duration,
      ease: "power2.out",
      onUpdate: () => {
        el.textContent = nf.format(counter.n);
      },
      onComplete: () => {
        // Snap to the exact value: easing lands fractionally short, and a KPI
        // that settles on 1,846 instead of 1,847 is simply wrong.
        el.textContent = nf.format(value);
      },
    });

    return () => {
      tween.kill();
      el.textContent = nf.format(value);
    };
  }, [value, duration, nf, reduced]);

  return (
    <span ref={ref} className={className}>
      {nf.format(value)}
    </span>
  );
}

/**
 * Press feedback for a card-sized target.
 *
 * Scales down on pointer-down and springs back on release. Pointer events
 * rather than mouse events so it works under touch, and the tween is killed on
 * unmount so a navigation mid-press cannot leave a scaled ghost behind.
 */
export function PressCard({
  children,
  className,
  ...props
}: React.ComponentProps<"div">) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = usePrefersReducedMotion();

  const to = (scale: number, ease: string, duration: number) => {
    if (reduced || !ref.current) return;
    gsap.to(ref.current, { scale, duration, ease, overwrite: true });
  };

  return (
    <div
      ref={ref}
      className={className}
      onPointerDown={() => to(0.975, EASE_OUT, 0.12)}
      onPointerUp={() => to(1, EASE_BOUNCE, 0.4)}
      onPointerLeave={() => to(1, EASE_OUT, 0.2)}
      onPointerCancel={() => to(1, EASE_OUT, 0.2)}
      {...props}
    >
      {children}
    </div>
  );
}

/**
 * Zoom-in entrance for a drill-down view.
 *
 * Used by the stock detail page so arriving from a grid row reads as pushing
 * *into* that row rather than as an unrelated page replacing it. Deliberately
 * short and slightly overshooting; a slow zoom on a page of financials is an
 * obstacle, not delight.
 */
export function ZoomIn({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ctx = gsap.context(() => {
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.from(el, {
          opacity: 0,
          scale: 0.97,
          y: 8,
          duration: 0.45,
          ease: EASE_BOUNCE,
          clearProps: "transform,opacity",
        });
      });
    }, el);
    return () => ctx.revert();
  }, []);

  return (
    <div ref={ref} className={cn(className)}>
      {children}
    </div>
  );
}
