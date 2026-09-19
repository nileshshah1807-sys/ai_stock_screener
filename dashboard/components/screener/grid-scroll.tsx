"use client";

import { useLayoutEffect, useRef, type ReactNode } from "react";
import { usePathname, useSearchParams } from "next/navigation";

/**
 * The grid's scroll container, with its position remembered per view.
 *
 * The browser restores the *window's* scroll on Back, but the grid scrolls
 * inside its own bounded container (see `.grid-scroll`), and that container is
 * a fresh element every time the page mounts -- so returning from a stock page
 * always landed at the top of the list. The position is saved to
 * sessionStorage on scroll, keyed by path and query string, and put back on
 * mount before the first paint.
 *
 * Keyed by the full query so a different sort, filter or page starts from its
 * own remembered place. A view with nothing saved is left exactly where it is:
 * hiding a column or switching density must not throw the reader back to the
 * top, which is its own small bug.
 *
 * sessionStorage, not localStorage: a position is only meaningful for the tab
 * that scrolled it, and it should not outlive the session.
 */
export function GridScroll({ children }: { children: ReactNode }) {
  const node = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const key = `grid-scroll:${pathname}?${search}`;

  useLayoutEffect(() => {
    const element = node.current;
    if (!element) return;

    try {
      const saved = window.sessionStorage.getItem(key);
      if (saved) {
        const { top, left } = JSON.parse(saved) as { top: number; left: number };
        if (Number.isFinite(top)) element.scrollTop = top;
        if (Number.isFinite(left)) element.scrollLeft = left;
      }
    } catch {
      // Storage disabled or a malformed entry: start wherever the grid is.
    }

    let frame = 0;
    const save = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        try {
          window.sessionStorage.setItem(
            key,
            JSON.stringify({ top: element.scrollTop, left: element.scrollLeft }),
          );
        } catch {
          // Quota or privacy mode: losing the position is harmless.
        }
      });
    };
    element.addEventListener("scroll", save, { passive: true });
    return () => {
      element.removeEventListener("scroll", save);
      cancelAnimationFrame(frame);
    };
  }, [key]);

  return (
    <div ref={node} className="grid-scroll">
      {children}
    </div>
  );
}
