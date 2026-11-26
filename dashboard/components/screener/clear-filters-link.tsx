"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

import { clearedHref } from "@/lib/clear-href.mjs";

/**
 * The way out of an empty grid: the same page without its filters, or without
 * just `drop` (a search). The search inputs follow the URL, so they clear too.
 */
export function ClearFiltersLink({ drop, children = "Clear filters" }: { drop?: string[]; children?: React.ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  return (
    <Link
      href={clearedHref(pathname, searchParams.toString(), drop)}
      scroll={false}
      // The Results and Concalls pages' own "Clear search and filters" link.
      className="mt-3 inline-block rounded text-xs font-medium underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {children}
    </Link>
  );
}
