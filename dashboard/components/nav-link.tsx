"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/**
 * Nav item that marks the current location for both sighted users (colour
 * and the underline under it) and assistive technology (aria-current),
 * rather than relying on colour alone.
 *
 * The item paints no fill of its own. The selection is the underline that
 * GlassTrack slides beneath whichever item is current, so the item only has
 * to state which one it is. Below `md` the nav is a tab bar at the bottom of
 * the screen, and each item stacks its icon over its label; from `md` it is
 * a row of text tabs in the header.
 *
 * Press feedback is on pointer-down: the item dips the moment it is touched,
 * in ~70ms, and springs back on release.
 */
export function NavLink({
  href,
  exact = false,
  also,
  onNavigate,
  children,
}: {
  href: string;
  /**
   * Other paths this item is current on. The Tools tab links to the first
   * tool and must stay lit on every other one.
   */
  also?: readonly string[];
  /**
   * Match the path exactly rather than by prefix.
   *
   * Needed since destinations gained a market segment: the screener lives at
   * `/ind`, which is a prefix of `/ind/watchlists`, `/ind/movers` and every
   * other sibling. Without this the screener tab would read as active on
   * every page in the market.
   */
  exact?: boolean;
  onNavigate?: () => void;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const under = (path: string) => pathname === path || pathname.startsWith(`${path}/`);
  const active = exact ? pathname === href : under(href) || (also ?? []).some(under);

  return (
    <Link
      href={href}
      /*
       * The full route, data included, not just the shell down to loading.tsx
       * (the default for a dynamic route). Measured: a first visit spent
       * 0.3-2s in the page's queries after the skeleton appeared; a
       * prefetched one renders in under 70ms. Bounded: five destinations, and
       * staleTimes.dynamic holds each for 60s, so it is not refetched on every
       * render.
       */
      prefetch
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group/nav relative flex flex-1 items-center justify-center rounded-md",
        "flex-col gap-1 px-2 py-2 text-[0.6875rem] leading-none font-medium",
        "md:h-full md:flex-none md:flex-row md:gap-2 md:px-3 md:py-0 md:text-sm",
        "min-h-14 md:min-h-0",
        "transition-[color,transform] duration-(--duration-spring-bouncy) ease-(--ease-spring)",
        "active:scale-[0.96] active:duration-(--duration-press) active:ease-out",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
        // Weight never changes with the selection, so the row does not
        // reflow under the sliding underline; colour and the underline carry
        // it. On the phone's tab bar the current item also takes the accent.
        active
          ? "text-foreground max-md:text-brand"
          : "text-muted-foreground hover:text-foreground",
        "[&>svg]:size-5 md:[&>svg]:hidden",
      )}
    >
      {children}
    </Link>
  );
}
