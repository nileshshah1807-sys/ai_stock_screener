"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/**
 * Nav item that marks the current location for both sighted users (weight and
 * background) and assistive technology (aria-current), rather than relying on
 * colour alone.
 *
 * `rail` is the sidebar presentation: full width, icon and label side by side.
 * The default is the compact horizontal form used in the mobile top bar.
 */
export function NavLink({
  href,
  rail = false,
  onNavigate,
  children,
}: {
  href: string;
  rail?: boolean;
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
        "flex items-center gap-3 rounded-md text-sm transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
        // 44px min height in the rail keeps every target at the platform
        // minimum without needing a separate hit area.
        rail ? "min-h-11 px-3 py-2" : "min-h-9 px-2.5 py-1.5",
        active
          ? "bg-accent font-medium text-accent-foreground"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {children}
    </Link>
  );
}
