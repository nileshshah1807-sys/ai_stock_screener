"use client";

import { useLayoutEffect, useRef } from "react";
import gsap from "gsap";

/**
 * The account page's frame: the landing and pricing pages' one green accent
 * (scoped here, so the app's own tokens are untouched) and one arrival, the
 * sections rising in. Content is in the HTML; gsap.from() sets the start state at
 * runtime, before paint, and reduced motion is a real branch that runs nothing.
 * Nothing animates a layout property.
 */
export function AccountMotion({ children }: { children: React.ReactNode }) {
  const root = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.from(root.current?.querySelectorAll("[data-arrive]") ?? [], {
          opacity: 0,
          y: 14,
          duration: 0.55,
          ease: "expo.out",
          stagger: 0.07,
          clearProps: "transform,opacity",
        });
      });
    }, root);
    return () => ctx.revert();
  }, []);

  return (
    <div ref={root} className="[--brand-soft:color-mix(in_oklab,var(--rating-strong-buy)_12%,var(--card))] [--brand:var(--rating-strong-buy)]">
      {children}
    </div>
  );
}
