"use client";

import { useSearchParams } from "next/navigation";
import { Download } from "lucide-react";

/**
 * CSV export for the current filter set.
 *
 * Reads the query string on the client so this can live in the screener layout
 * alongside the other filter chrome. A Server Component here would force the
 * whole layout to depend on searchParams, which is exactly what we moved out of
 * the render path -- the layout would then re-render on every sort click.
 */
export function ExportLink() {
  const searchParams = useSearchParams();

  const params = new URLSearchParams(searchParams.toString());
  params.delete("page");
  const query = params.toString();

  return (
    <a
      href={`/api/export${query ? `?${query}` : ""}`}
      className="inline-flex h-9 items-center gap-1.5 rounded-full border bg-muted px-4 text-sm font-medium transition-colors duration-(--duration-fast) hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Download className="size-3.5" aria-hidden />
      <span className="hidden sm:inline">Export CSV</span>
    </a>
  );
}
