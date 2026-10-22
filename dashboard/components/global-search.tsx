"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";

import { useMarketPath } from "@/components/market-provider";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { StockPicker, useStockPickerShortcut } from "@/components/screener/stock-picker";

/**
 * Search the market's stocks and indices from anywhere: the header's
 * magnifier, the screener toolbar's field, or ⌘K.
 *
 * One dialog for the whole shell, mounted once in AppShell, so every trigger
 * opens the same picker and the shortcut has a single owner. Triggers reach
 * it by a window event rather than a context, because the header and <main>
 * share no client parent to hold one. Picking a stock opens its page and
 * picking an index opens the index's. Nothing is fetched until the first
 * open; the indices come in the same cached request as the stocks.
 */

const OPEN_EVENT = "winnow:open-search";

/** Open the header's search, from any trigger on the page. */
export function openSearch() {
  window.dispatchEvent(new Event(OPEN_EVENT));
}

export function GlobalSearch() {
  const router = useRouter();
  const marketPath = useMarketPath();
  const [open, setOpen] = useState(false);

  const close = useCallback(() => setOpen(false), []);
  // Priority 0: a page's own picker (the watchlist's "Add stocks") keeps ⌘K.
  useStockPickerShortcut(open, setOpen, close, 0);

  useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener(OPEN_EVENT, show);
    return () => window.removeEventListener(OPEN_EVENT, show);
  }, []);

  return (
    <StockPicker
      open={open}
      onClose={close}
      title="Search stocks and indices"
      placeholder="Stock, company or index…"
      onPick={(symbol) => router.push(marketPath(`/stocks/${encodeURIComponent(symbol)}`))}
      onPickIndex={(index) => router.push(marketPath(`/indices/${index.slug}`))}
      hint="Type a ticker, a company or an index. Enter opens it; ↑↓ to move."
    />
  );
}

/**
 * Search, at the head of the header's account controls: a magnifier on
 * narrow screens, and from lg a field-shaped button that names what it finds
 * and its shortcut, which is where a reader of this category of tool looks
 * for it. Either way it opens the same picker.
 */
export function GlobalSearchButton() {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      onClick={openSearch}
      className={cn(
        "text-muted-foreground hover:text-foreground",
        "lg:mr-1.5 lg:w-56 lg:justify-start lg:gap-2 lg:border-input lg:bg-muted/60 lg:px-2.5 lg:font-normal lg:hover:bg-muted",
      )}
      aria-label="Search stocks and indices"
      aria-keyshortcuts="Meta+K Control+K"
      title="Search  ⌘K"
    >
      <Search className="size-4" aria-hidden />
      <span className="hidden text-sm lg:inline">Search stocks…</span>
      <kbd className="ml-auto hidden rounded-[4px] border bg-card px-1.5 text-[10px] leading-4 font-medium text-muted-foreground lg:inline">
        ⌘K
      </kbd>
    </Button>
  );
}
