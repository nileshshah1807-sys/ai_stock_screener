"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

type Box = { x: number; y: number; w: number; h: number };

/**
 * A glass capsule whose selected item is marked by a lens that glides between
 * items, the way an iOS segmented control or tab bar does.
 *
 * Two details carry the feel, and both are about latency:
 *
 * 1. The lens moves on pointer-down, not on navigation. A route change costs
 *    a server round trip; waiting for `aria-current` to move would put that
 *    whole round trip between the press and any visible response. Instead the
 *    lens starts travelling the instant the finger lands, and the route
 *    catches up behind it. If the press is cancelled (dragged off, scrolled),
 *    the lens returns to the real current item.
 *
 * 2. It is interruptible. The lens is positioned with a transform under a CSS
 *    transition, and an interrupted transition retargets from its current
 *    on-screen value -- so pressing a second item while the lens is still
 *    moving redirects it mid-flight rather than finishing the first trip.
 *
 * Items are the children; the current one is whichever carries
 * `aria-current` (links), `aria-selected="true"` (tabs) or
 * `aria-checked="true"` (a radio group, e.g. a segmented control). The track watches
 * those attributes, so it follows a selection that moves without a route
 * change -- a client-side tab switch -- as well as one that does. The very
 * first placement is made without a transition, so the lens appears under the
 * current item rather than sliding in from 0,0.
 */
const SELECTED =
  '[aria-current]:not([aria-current="false"]), [aria-selected="true"], [aria-checked="true"]';

export function GlassTrack({
  label,
  role,
  className,
  lensClassName,
  onKeyDown,
  children,
}: {
  label: string;
  /**
   * `tablist` when the items are tabs, `radiogroup` when they are a
   * segmented choice, rather than navigation links.
   */
  role?: "tablist" | "radiogroup";
  className?: string;
  lensClassName?: string;
  onKeyDown?: React.KeyboardEventHandler<HTMLElement>;
  children: React.ReactNode;
}) {
  const track = useRef<HTMLElement>(null);
  const pathname = usePathname();
  const [box, setBox] = useState<Box | null>(null);
  const [animate, setAnimate] = useState(false);
  const pending = useRef<HTMLElement | null>(null);

  const measure = (el: Element | null) => {
    const root = track.current;
    if (!root || !(el instanceof HTMLElement)) return;
    setBox({ x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight });
  };

  const current = () => track.current?.querySelector(SELECTED) ?? null;

  // Settle on the real current item whenever the route changes, and follow it
  // when the track reflows (a font swap, the viewport crossing a breakpoint).
  useLayoutEffect(() => {
    pending.current = null;
    measure(current());
    const root = track.current;
    if (!root) return;
    const ro = new ResizeObserver(() => measure(pending.current ?? current()));
    ro.observe(root);
    const mo = new MutationObserver(() => {
      pending.current = null;
      measure(current());
    });
    mo.observe(root, {
      subtree: true,
      attributes: true,
      attributeFilter: ["aria-current", "aria-selected", "aria-checked"],
    });
    return () => {
      ro.disconnect();
      mo.disconnect();
    };
  }, [pathname]);

  // Transitions switch on only after the first placement has painted.
  useLayoutEffect(() => {
    if (!box || animate) return;
    const id = requestAnimationFrame(() => setAnimate(true));
    return () => cancelAnimationFrame(id);
  }, [box, animate]);

  const release = () => {
    if (!pending.current) return;
    pending.current = null;
    measure(current());
  };

  const onPointerDown = (event: React.PointerEvent) => {
    // A modified click opens a new tab and leaves this page where it is, so
    // the lens must not move for it.
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
    const item = (event.target as Element).closest("a,button");
    if (!(item instanceof HTMLElement) || !track.current?.contains(item)) return;
    pending.current = item;
    measure(item);
    // Lifting outside the item is a cancelled tap: no navigation follows, so
    // nothing else would ever bring the lens back. Dragging a link off itself
    // starts a native link drag, which ends in neither pointerup nor a click,
    // so dragstart and pointercancel count as cancellation too.
    const done = (end: Event) => {
      window.removeEventListener("pointerup", done);
      window.removeEventListener("pointercancel", done);
      window.removeEventListener("dragstart", done);
      const landed = end.type === "pointerup" && end.target instanceof Node && item.contains(end.target);
      if (!landed) release();
    };
    window.addEventListener("pointerup", done);
    window.addEventListener("pointercancel", done);
    window.addEventListener("dragstart", done);
  };

  return (
    <nav
      ref={track}
      aria-label={label}
      role={role}
      className={cn("glass relative isolate flex rounded-full", className)}
      onPointerDown={onPointerDown}
      onKeyDown={onKeyDown}
      onKeyUp={(event) => {
        if (event.key === "Enter") measure(event.target as Element);
      }}
    >
      {box ? (
        <span
          aria-hidden
          className={cn(
            "lens pointer-events-none absolute top-0 left-0 -z-10 rounded-full",
            animate &&
              "transition-[transform,width,height] duration-(--duration-spring-bouncy) ease-(--ease-spring) motion-reduce:transition-none",
            lensClassName,
          )}
          style={{
            width: box.w,
            height: box.h,
            transform: `translate3d(${box.x}px, ${box.y}px, 0)`,
          }}
        />
      ) : null}
      {children}
    </nav>
  );
}
