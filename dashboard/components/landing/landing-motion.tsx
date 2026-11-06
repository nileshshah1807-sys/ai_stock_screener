"use client";

import { useEffect } from "react";

/**
 * The landing page's scroll motion, driven by data attributes so the server
 * components stay plain markup:
 *
 *   data-parallax="0.2"   drifts with scroll (fraction of 300px of travel)
 *   data-reveal           rises into place once, as it enters
 *   data-stagger          its children rise in sequence, as the group enters
 *   data-bar              a bar that grows from its left edge
 *   data-count            a figure that counts up to the text it already holds
 *   data-progress         a bar that tracks how far down the page you are
 *   data-spotlight        a section whose light follows the pointer
 *
 * Same rules as components/motion.tsx: every effect is gsap.from(), so content
 * is never hidden by CSS and is simply there without JS; reduced motion runs
 * nothing at all; only transforms and opacity move, so nothing shifts layout.
 * ScrollTrigger is imported on demand to keep it out of the first paint.
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
          const enter = { start: "top 94%", once: true } as const;
          // Already on screen at load: leave it be. Hiding it to reveal it a
          // beat later is a flicker, not a reveal.
          const below = (el: Element) => el.getBoundingClientRect().top > window.innerHeight * 0.94;

          gsap.utils.toArray<HTMLElement>("[data-parallax]").forEach((el) => {
            const speed = Number(el.dataset.parallax) || 0.15;
            gsap.fromTo(
              el,
              { y: -speed * 300 },
              {
                y: speed * 300,
                ease: "none",
                scrollTrigger: { trigger: el.parentElement ?? el, start: "top bottom", end: "bottom top", scrub: 0.6 },
              },
            );
          });

          gsap.utils.toArray<HTMLElement>("[data-reveal]").filter(below).forEach((el) => {
            gsap.from(el, { opacity: 0, y: 28, duration: 0.8, ease: "expo.out", clearProps: "transform,opacity", scrollTrigger: { trigger: el, ...enter } });
          });

          gsap.utils.toArray<HTMLElement>("[data-stagger]").filter(below).forEach((el) => {
            const kids = Array.from(el.children);
            gsap.from(kids, {
              opacity: 0,
              y: 22,
              duration: 0.7,
              ease: "expo.out",
              stagger: Math.min(0.09, 0.45 / Math.max(1, kids.length)),
              clearProps: "transform,opacity",
              scrollTrigger: { trigger: el, ...enter },
            });
          });

          gsap.utils.toArray<HTMLElement>("[data-bar]").filter(below).forEach((el) => {
            gsap.from(el, { scaleX: 0, transformOrigin: "left center", duration: 1, ease: "expo.out", delay: 0.15, scrollTrigger: { trigger: el, ...enter } });
          });

          gsap.utils.toArray<HTMLElement>("[data-count]").forEach((el) => {
            const text = el.textContent ?? "";
            const end = Number.parseFloat(text.replace(/,/g, ""));
            if (!Number.isFinite(end)) return;
            const counter = { n: 0 };
            gsap.to(counter, {
              n: end,
              duration: 1.1,
              ease: "power2.out",
              onUpdate: () => {
                el.textContent = Math.round(counter.n).toLocaleString("en-IN");
              },
              // Land on the exact written text: easing can stop a unit short.
              onComplete: () => {
                el.textContent = text;
              },
              scrollTrigger: { trigger: el, ...enter },
            });
          });

          const bar = root.querySelector<HTMLElement>("[data-progress]");
          if (bar) {
            gsap.fromTo(bar, { scaleX: 0 }, { scaleX: 1, ease: "none", scrollTrigger: { trigger: document.body, start: "top top", end: "bottom bottom", scrub: 0.2 } });
          }

          // The light under a section follows the pointer.
          const cleanups = Array.from(root.querySelectorAll<HTMLElement>("[data-spotlight]")).map((el) => {
            let frame = 0;
            const move = (e: PointerEvent) => {
              cancelAnimationFrame(frame);
              frame = requestAnimationFrame(() => {
                const r = el.getBoundingClientRect();
                el.style.setProperty("--mx", `${e.clientX - r.left}px`);
                el.style.setProperty("--my", `${e.clientY - r.top}px`);
              });
            };
            el.addEventListener("pointermove", move);
            return () => {
              cancelAnimationFrame(frame);
              el.removeEventListener("pointermove", move);
            };
          });
          return () => cleanups.forEach((fn) => fn());
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
