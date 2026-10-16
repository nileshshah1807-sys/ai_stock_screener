"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
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
 * 3. Nothing animates a layout property -- with one exception, disclosure
 *    (SmoothDetails, useExpand). Opening a panel must move what is below it;
 *    the only choice is whether that happens in one frame or over a few
 *    hundred milliseconds, and a jump is what loses the reader's place. The
 *    tween is confined to the one box that opens, which clips its own content,
 *    and is cleared the moment it lands, so the box goes back to sizing
 *    itself.
 */

/*
 * Shared easing.
 *
 * Overshoot is reserved for motion the user's own gesture set going -- a card
 * springing back from a press. Content that simply arrives settles without
 * it: a panel that bounces into place on its own reads as the interface
 * performing, not responding. EASE_OUT is expo rather than power3 because its
 * long, soft tail is the closest bezier to a critically damped spring.
 */
const EASE_RELEASE = "back.out(1.2)";
const EASE_OUT = "expo.out";

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
          duration: bounce ? 0.55 : 0.5,
          ease: bounce ? EASE_RELEASE : EASE_OUT,
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
/**
 * Figures already counted in this tab, by the caller's `once` key.
 *
 * Module scope, so it outlives the component: the screener's tiles unmount on
 * every visit to another page and remount on the way back, and re-counting
 * from zero each time made a page that was on screen in ~70ms read as one
 * still loading for another second. A reload starts the count afresh.
 */
const counted = new Set<string>();

export function CountUp({
  value,
  locale = "en-IN",
  duration = 1.1,
  once,
  className,
}: {
  value: number;
  locale?: string;
  duration?: number;
  /** Count only the first time this key is shown in the tab. */
  once?: string;
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
    if (once !== undefined) {
      if (counted.has(once)) return;
      counted.add(once);
    }

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
  }, [value, duration, nf, reduced, once]);

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
      onPointerDown={() => to(0.975, "power2.out", 0.07)}
      onPointerUp={() => to(1, EASE_RELEASE, 0.45)}
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
 * short and without overshoot; a slow or bouncing zoom on a page of
 * financials is an obstacle, not delight.
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
          duration: 0.5,
          ease: EASE_OUT,
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

/*
 * Disclosure timing. Opening decelerates on power3 rather than the expo
 * curve content arrives on: expo covers 80% of the distance in the first
 * quarter, which on a panel the reader is watching grow reads as a jump with
 * a long settle. Closing is shorter and eases in and out, because a panel the
 * reader dismissed should get out of the way rather than linger.
 */
const OPEN = { duration: 0.45, ease: "power3.out" };
const CLOSE = { duration: 0.28, ease: "power3.inOut" };

/**
 * Every `<details>` in the app, opened and closed with motion.
 *
 * Mounted once, in the shell, as a single delegated click listener -- so a
 * disclosure rendered on the server needs no client component of its own and
 * costs nothing until it is pressed. Without JS, or with reduced motion, the
 * browser's own toggle runs untouched.
 *
 * The `<details>` box itself is tweened between its closed and open heights.
 * While it closes it is still `[open]`, so `data-closing` is set for the
 * stylesheet to turn its chevron back on the press (globals.css).
 */
export function SmoothDetails() {
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    if (reduced) return;
    const running = new WeakMap<HTMLDetailsElement, gsap.core.Tween>();

    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented) return;
      const summary = (event.target as Element | null)?.closest?.("summary");
      const details = summary?.parentElement;
      if (!(details instanceof HTMLDetailsElement) || summary !== details.firstElementChild) return;
      if (details.hasAttribute("data-instant")) return;
      event.preventDefault();

      const start = details.offsetHeight;
      running.get(details)?.kill();
      const closing = details.open && !details.hasAttribute("data-closing");

      // Measure the end state by setting it for one synchronous layout.
      details.removeAttribute("data-closing");
      details.open = !closing;
      const end = details.offsetHeight;
      details.open = true;
      if (closing) details.setAttribute("data-closing", "");

      const content = Array.from(details.children).filter((child) => child !== summary);
      gsap.set(details, { height: start, overflow: "hidden" });
      if (!closing) gsap.fromTo(content, { opacity: 0, y: -4 }, { opacity: 1, y: 0, ...OPEN, clearProps: "opacity,transform" });
      const tween = gsap.to(details, {
        height: end,
        ...(closing ? CLOSE : OPEN),
        onComplete: () => {
          if (closing) {
            details.open = false;
            details.removeAttribute("data-closing");
          }
          gsap.set(details, { clearProps: "height,overflow" });
          running.delete(details);
        },
      });
      running.set(details, tween);
    };

    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, [reduced]);

  return null;
}

/**
 * Height-animated mount and unmount for a panel that is not a `<details>`:
 * a list that grows, a table row that opens.
 *
 * Returns whether the content should be rendered at all -- it stays mounted
 * through the closing tween, then leaves the DOM, so a long collapsed list
 * costs nothing -- and a ref for the box to animate. Inside that box, any
 * `[data-expand]` descendants are animated instead of the box itself: a
 * `<tr>` cannot be given a height, but the cells' inner wrappers can.
 *
 * The first render is never animated: a panel open on arrival is just open.
 */
export function useExpand<T extends HTMLElement>(open: boolean) {
  const ref = useRef<T>(null);
  const reduced = usePrefersReducedMotion();
  const [mounted, setMounted] = useState(open);
  // With no closing tween to wait for, the content leaves with `open`.
  if (open !== mounted && (open || reduced)) setMounted(open);
  const first = useRef(true);

  useLayoutEffect(() => {
    const el = ref.current;
    if (first.current) {
      first.current = false;
      return;
    }
    if (!el || reduced) return;
    const nested = el.querySelectorAll<HTMLElement>("[data-expand]");
    const targets = nested.length ? Array.from(nested) : [el];
    gsap.killTweensOf(targets);
    if (open) {
      // Mid-close, the tween already left an inline height: grow from there
      // rather than snapping back to zero.
      for (const target of targets) {
        if (!target.style.height) gsap.set(target, { height: 0, opacity: 0 });
      }
      const tween = gsap.to(targets, {
        height: "auto",
        opacity: 1,
        overflow: "hidden",
        ...OPEN,
        clearProps: "height,opacity,overflow",
      });
      return () => {
        tween.kill();
      };
    }
    const tween = gsap.to(targets, {
      height: 0,
      opacity: 0,
      overflow: "hidden",
      ...CLOSE,
      onComplete: () => setMounted(false),
    });
    return () => {
      tween.kill();
    };
  }, [open, reduced]);

  return { ref, mounted: mounted || open };
}

/** `useExpand` as a box: renders `children` only while open or closing. */
export function Expand({
  open,
  children,
  className,
  id,
}: {
  open: boolean;
  children: React.ReactNode;
  className?: string;
  id?: string;
}) {
  const { ref, mounted } = useExpand<HTMLDivElement>(open);
  if (!mounted) return null;
  return (
    <div ref={ref} id={id} className={className}>
      {children}
    </div>
  );
}

/**
 * Fades its content in whenever `token` changes -- a list that arrives in a
 * box already holding its skeleton. Opacity only: the box does not move.
 */
export function FadeSwap({
  token,
  children,
  className,
}: {
  token: unknown;
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = usePrefersReducedMotion();
  const first = useRef(true);
  useLayoutEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    if (reduced || !ref.current) return;
    const tween = gsap.fromTo(
      ref.current,
      { opacity: 0, y: 6 },
      { opacity: 1, y: 0, duration: 0.36, ease: EASE_OUT, clearProps: "opacity,transform" },
    );
    return () => {
      tween.kill();
    };
  }, [token, reduced]);
  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}
