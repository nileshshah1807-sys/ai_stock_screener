"use client";

import { useEffect, type RefObject } from "react";
import type gsapType from "gsap";

/**
 * A pinned, scrubbed scene: the landing page's one scroll grammar. `build`
 * receives gsap and the scene element and returns a timeline; the scene holds
 * for about a screen of scrolling while the timeline plays with the scroll.
 *
 * The markup is always the END state, so without JS, or with reduced motion
 * (nothing runs at all), the scene is simply finished. gsap and ScrollTrigger
 * load on demand, after first paint. The pin is about one screen of travel,
 * and shorter on a phone, where holding the page for long reads as a stall.
 */
export function useScene(
  ref: RefObject<HTMLElement | null>,
  build: (gsap: typeof gsapType, root: HTMLElement) => gsap.core.Timeline,
) {
  useEffect(() => {
    let cancelled = false;
    let revert = () => {};
    (async () => {
      const [{ default: gsap }, { ScrollTrigger }] = await Promise.all([import("gsap"), import("gsap/ScrollTrigger")]);
      const root = ref.current;
      if (cancelled || !root) return;
      gsap.registerPlugin(ScrollTrigger);
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const phone = window.matchMedia("(max-width: 639px)").matches;
        ScrollTrigger.create({
          trigger: root,
          start: phone ? "center 55%" : "center center",
          end: phone ? "+=70%" : "+=100%",
          pin: true,
          scrub: 0.5,
          animation: build(gsap, root),
        });
      });
      revert = () => mm.revert();
    })();
    return () => {
      cancelled = true;
      revert();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- a scene is built once per mount
  }, []);
}
