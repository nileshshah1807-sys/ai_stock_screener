"use client";

import { useEffect, type RefObject } from "react";
import type gsapType from "gsap";

/** Phone (no pin); then the widths either side of `md`, where the scenes change layout (evening turns horizontal). */
const SCENE_RANGES = ["(max-width: 639px)", "(min-width: 640px) and (max-width: 767px)", "(min-width: 768px)"];

/**
 * A pinned, scrubbed scene: the landing page's one scroll grammar. `build`
 * receives gsap and the scene element and returns a timeline; the scene holds
 * for about a screen of scrolling while the timeline plays with the scroll.
 *
 * The markup is always the END state, so without JS, or with reduced motion
 * (nothing runs at all), the scene is simply finished. gsap and ScrollTrigger
 * load on demand, after first paint. The pin is about one screen of travel;
 * a phone is never pinned, the scene just plays as it scrolls past.
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
      // One build per layout range: crossing a breakpoint (a rotated phone, a resized window) reverts the
      // scene and builds it again, so its start state is read from the layout now showing, not the one at load.
      SCENE_RANGES.forEach((range, i) =>
        mm.add(`(prefers-reduced-motion: no-preference) and ${range}`, () => {
          // A phone holds nothing: the scene plays as it scrolls through the screen, so it is never blank.
          ScrollTrigger.create(
            i === 0
              ? { trigger: root, start: "top 85%", end: "bottom 55%", scrub: 0.5, animation: build(gsap, root) }
              : { trigger: root, start: "center center", end: "+=100%", pin: true, scrub: 0.5, animation: build(gsap, root) },
          );
        }),
      );
      revert = () => mm.revert();
    })();
    return () => {
      cancelled = true;
      revert();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- a scene is built once per mount
  }, []);
}
