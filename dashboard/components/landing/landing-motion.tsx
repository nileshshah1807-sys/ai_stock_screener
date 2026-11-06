"use client";

import { useEffect } from "react";

/**
 * The landing page's page-level motion, driven by data attributes so the
 * server components stay plain markup:
 *
 *   data-reveal     fades in once, as it enters (opacity only: nothing moves)
 *   data-progress   a bar that tracks how far down the page you are
 *
 * The pinned scenes (hero sieve, stage line, evening) are components/landing/
 * use-scene.ts. Same rules as components/motion.tsx: every effect is
 * gsap.from(), so content is never hidden by CSS and is simply there without
 * JS; reduced motion runs nothing at all. ScrollTrigger is imported on demand
 * to keep it out of the first paint.
 */
export function LandingMotion() {
  useEffect(() => {
    let revert = () => {};
    let cancelled = false;

    (async () => {
      const [{ default: gsap }, { ScrollTrigger }] = await Promise.all([import("gsap"), import("gsap/ScrollTrigger")]);
      if (cancelled) return;
      gsap.registerPlugin(ScrollTrigger);
      const root = document.querySelector<HTMLElement>(".landing");
      if (!root) return;

      const ctx = gsap.context(() => {
        const mm = gsap.matchMedia();
        mm.add("(prefers-reduced-motion: no-preference)", () => {
          // Already on screen at load: leave it be. Hiding it to reveal it a
          // beat later is a flicker, not a reveal.
          const below = (el: Element) => el.getBoundingClientRect().top > window.innerHeight * 0.94;
          gsap.utils.toArray<HTMLElement>("[data-reveal]").filter(below).forEach((el) => {
            gsap.from(el, { opacity: 0, duration: 0.8, ease: "expo.out", clearProps: "opacity", scrollTrigger: { trigger: el, start: "top 94%", once: true } });
          });
          const bar = root.querySelector<HTMLElement>("[data-progress]");
          if (bar) {
            gsap.fromTo(bar, { scaleX: 0 }, { scaleX: 1, ease: "none", scrollTrigger: { trigger: document.body, start: "top top", end: "bottom bottom", scrub: 0.2 } });
          }
        });
      }, root);

      revert = () => ctx.revert();
    })();

    return () => {
      cancelled = true;
      revert();
    };
  }, []);

  return null;
}
