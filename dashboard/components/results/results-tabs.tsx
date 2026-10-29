"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { GlassTrack } from "@/components/glass-track";
import { cn } from "@/lib/utils";

/**
 * The Results tool's two views: the season's cards, and the Analysis of how
 * the quarters compare. Links, since each has its own URL; the same track as
 * the Tools row above it.
 */
export function ResultsTabs({ base }: { base: string }) {
  const pathname = usePathname();
  const tabs = [
    { href: base, label: "Results", active: pathname === base },
    { href: `${base}/analysis`, label: "Analysis", active: pathname.startsWith(`${base}/analysis`) },
  ];
  return (
    <GlassTrack label="Results views" className="w-max gap-0.5 p-0.5">
      {tabs.map(({ href, label, active }) => (
        <Link
          key={href}
          href={href}
          aria-current={active ? "page" : undefined}
          className={cn(
            "inline-flex min-h-7 items-center justify-center rounded-md px-3 text-xs font-medium leading-none",
            "transition-[color,transform] duration-(--duration-spring-bouncy) ease-(--ease-spring)",
            "active:scale-[0.92] active:duration-(--duration-press) active:ease-out",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
            active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {label}
        </Link>
      ))}
    </GlassTrack>
  );
}
