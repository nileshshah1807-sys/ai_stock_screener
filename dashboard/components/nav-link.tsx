"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/**
 * Nav item that marks the current location for both sighted users (weight,
 * colour and the lens behind it) and assistive technology (aria-current),
 * rather than relying on colour alone.
 *
 * The item paints no fill of its own. The selection is the lens that
 * GlassTrack slides beneath whichever item is current, so the item only has
 * to state which one it is. Below `md` the nav is a floating tab bar, and each
 * item stacks its icon over its label the way an iOS tab bar does; from `md`
 * it is a horizontal capsule in the header.
 *
 * Press feedback is on pointer-down: the item dips the moment it is touched,
 * in ~70ms, and springs back on release.
 */
export function NavLink({
  href,
  exact = false,
  onNavigate,
  children,
}: {
  href: string;
  /**
   * Match the path exactly rather than by prefix.
   *
   * Needed since destinations gained a market segment: the screener lives at
   * `/nse`, which is a prefix of `/nse/watchlists`, `/nse/movers` and every
   * other sibling. Without this the screener pill would read as active on
   * every page in the market.
   */
  exact?: boolean;
  onNavigate?: () => void;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const active = exact
    ? pathname === href
    : pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group/nav relative flex flex-1 items-center justify-center rounded-full",
        "flex-col gap-0.5 px-2 py-1.5 text-[0.6875rem] leading-none tracking-[0.01em]",
        "md:flex-row xl:flex-none md:gap-2 md:px-4 md:py-2 md:text-sm md:tracking-normal",
        "min-h-12 md:min-h-10",
        "transition-[color,transform] duration-(--duration-spring-bouncy) ease-(--ease-spring)",
        "active:scale-[0.94] active:duration-(--duration-press) active:ease-out",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
        active
          ? "font-semibold text-foreground"
          : "font-medium text-muted-foreground hover:text-foreground",
        "[&>svg]:size-5 md:[&>svg]:size-4",
      )}
    >
      {children}
    </Link>
  );
}
