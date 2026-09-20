"use client";

import { useEffect } from "react";

/**
 * j / k / Enter traversal of the grid.
 *
 * The grid already highlights `focus-within` on the row band, so moving focus
 * between the row links is all this needs to do -- the highlight, the scroll and
 * Enter-to-open all follow from the browser's own behaviour for a focused
 * anchor. That is why this moves focus rather than tracking a selected index in
 * state: there is no second source of truth to keep in sync, and a row reached
 * by Tab behaves identically to one reached by j.
 *
 * Renders nothing. It is a listener with a component's lifecycle, mounted inside
 * the grid panel so it unmounts with the grid rather than outliving it on a
 * route change.
 */

/** True when the keystroke belongs to whatever the user is typing in. */
function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

export function GridKeyboard() {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      // Never shadow a browser or OS shortcut. Ctrl+J and Cmd+K in particular
      // are already spoken for, and stealing them would be worse than having no
      // shortcut at all.
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
        return;
      }
      if (event.key !== "j" && event.key !== "k") return;
      if (isTyping(event.target)) return;

      const links = Array.from(
        document.querySelectorAll<HTMLAnchorElement>("[data-row-link]"),
      );
      if (!links.length) return;

      const current = links.indexOf(
        document.activeElement as HTMLAnchorElement,
      );
      // Not currently on a row: j starts at the top and k at the bottom, which
      // is what the direction of the key already implies.
      const next =
        current === -1
          ? event.key === "j"
            ? 0
            : links.length - 1
          : Math.min(
              links.length - 1,
              Math.max(0, current + (event.key === "j" ? 1 : -1)),
            );

      // Only now, once there is definitely something to move to. Calling this
      // earlier would swallow a `j` typed into a page that has no grid.
      event.preventDefault();
      links[next].focus();
      // The sticky header would otherwise cover the row that just took focus.
      // `nearest` leaves an already-visible row where it is instead of yanking
      // the viewport on every keystroke.
      links[next].scrollIntoView({ block: "nearest" });
    };

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  return null;
}
