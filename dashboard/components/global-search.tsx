"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";

import { useMarketPath } from "@/components/market-provider";
import { Button } from "@/components/ui/button";
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

/** The magnifier in the header's account capsule. */
export function GlobalSearchButton() {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      onClick={openSearch}
      className="rounded-full hover:bg-(--control-hover)"
      aria-label="Search stocks and indices"
      aria-keyshortcuts="Meta+K Control+K"
      title="Search  ⌘K"
    >
      <Search className="size-4" aria-hidden />
    </Button>
  );
}
