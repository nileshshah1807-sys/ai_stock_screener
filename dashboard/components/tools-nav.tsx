"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { GlassTrack } from "@/components/glass-track";
import { marketPath, type Market } from "@/lib/markets";
import { TOOLS } from "@/lib/tools";
import { cn } from "@/lib/utils";

/**
 * Which tool is open, as a second row of navigation under the header.
 *
 * Links on a glass track, the same control as the primary nav and the market
 * switch: all three say "one of these is current", and each tool has its own
 * URL. It is the smaller size of the three because it qualifies the Tools tab
 * above it rather than competing with it.
 */
export function ToolsNav({ market }: { market: Market }) {
  const pathname = usePathname();

  return (
    <GlassTrack label="Tools" className="w-max gap-0.5 p-1">
      {TOOLS.map(({ path, label, icon: Icon }) => {
        const href = marketPath(market.slug, path);
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={path}
            href={href}
            // Prefetched in full, like the primary nav (nav-link.tsx).
            prefetch
            aria-current={active ? "page" : undefined}
            className={cn(
              "inline-flex min-h-8 items-center justify-center gap-1.5 rounded-full",
              "px-3.5 text-xs font-semibold leading-none",
              "transition-[color,transform] duration-(--duration-spring-bouncy) ease-(--ease-spring)",
              "active:scale-[0.92] active:duration-(--duration-press) active:ease-out",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
              active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-3.5 shrink-0" aria-hidden />
            {label}
          </Link>
        );
      })}
    </GlassTrack>
  );
}
