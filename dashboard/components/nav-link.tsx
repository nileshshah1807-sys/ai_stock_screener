"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/**
 * Nav item that marks the current location for both sighted users (weight and
 * background) and assistive technology (aria-current), rather than relying on
 * colour alone.
 *
 *
 * Presentation follows the Figma nav: a fully rounded pill, the active one
 * filled solid against a recessed track. The mock's active pill is black on a
 * near-white track, which is exactly what `bg-primary` resolves to in light
 * mode -- and it inverts correctly in dark mode rather than leaving a black
 * pill on a black rail.
 *
 * The icon carries a slide on hover. It is 2px of travel on a single element,
 * which reads as responsiveness on a target the user is already pointing at
 * without turning the sidebar into an animation.
 */
export function NavLink({
  href,
  onNavigate,
  children,
}: {
  href: string;
  onNavigate?: () => void;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const active = href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group/nav relative flex items-center gap-3 rounded-full text-sm",
        "transition-[background-color,color,box-shadow] duration-(--duration-base) ease-(--ease-standard)",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
        // The mock's pill is 36px tall. Rounded up to 40 so the target clears
        // the platform minimum without a separate hit area, and so the row of
        // pills still fits the header at the mock's own proportions.
        "min-h-10 px-5 py-2",
        active
          ? "bg-primary font-medium text-primary-foreground shadow-xs"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
        "[&>svg]:transition-transform [&>svg]:duration-(--duration-base) [&>svg]:ease-(--ease-spring)",
        !active && "hover:[&>svg]:translate-x-0.5",
      )}
    >
      {children}
    </Link>
  );
}
