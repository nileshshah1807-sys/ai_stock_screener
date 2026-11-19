"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { GlassTrack } from "@/components/glass-track";
import { MARKET_PAGES } from "@/lib/market-pages";
import { marketPath, type Market } from "@/lib/markets";
import { TOOLS } from "@/lib/tools";
import { cn } from "@/lib/utils";

/** The header tabs that open onto a row of pages; the layout names which by key (icons cannot cross from a server layout). */
const GROUPS = { Tools: TOOLS, Market: MARKET_PAGES } as const;

/**
 * Which page of a header tab is open (Tools, Market), as a second row of
 * navigation under the header.
 *
 * Links on a glass track, the same control as the primary nav and the market
 * switch: all three say "one of these is current", and each page has its own
 * URL. It is the smaller size of the three because it qualifies the tab
 * above it rather than competing with it.
 */
export function SubNav({ group, market, admin }: { group: keyof typeof GROUPS; market: Market; admin: boolean }) {
  const pathname = usePathname();

  return (
    <GlassTrack label={group} className="w-max max-w-full gap-0.5 overflow-x-auto p-0.5">
      {GROUPS[group].filter((page) => admin || !page.adminOnly).map(({ path, label, icon: Icon }) => {
        const href = marketPath(market.slug, path);
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link prefetch={false}
            key={path}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "inline-flex min-h-7 items-center justify-center gap-1.5 rounded-md",
              "px-3 text-xs font-medium leading-none",
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
