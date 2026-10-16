"use client";

import { Search } from "lucide-react";

import { openSearch } from "@/components/global-search";
import { Button } from "@/components/ui/button";

/**
 * The screener toolbar's search field.
 *
 * A second trigger for the header's search (GlobalSearch) rather than a
 * picker of its own: one dialog and one owner for ⌘K, and the same results
 * -- stocks and indices -- whichever is pressed.
 */
export function StockSearch() {
  return (
    <Button
      variant="outline"
      onClick={openSearch}
      className="justify-start gap-2 text-muted-foreground sm:min-w-56"
    >
      <Search className="size-3.5" aria-hidden />
      <span className="hidden sm:inline">Search stocks &amp; indices…</span>
      <kbd className="ml-auto hidden rounded border bg-muted px-1.5 font-mono text-[10px] sm:inline">
        ⌘K
      </kbd>
    </Button>
  );
}
