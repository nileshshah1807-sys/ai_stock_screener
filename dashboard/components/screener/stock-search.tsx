"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  StockPicker,
  useStockPickerShortcut,
} from "@/components/screener/stock-picker";

/**
 * Jump to a stock from anywhere in the screener.
 *
 * The dialog, the ranking and the index fetch live in StockPicker, shared with
 * the watchlist's add control. All this contributes is the trigger and the verb:
 * picking a stock navigates to it.
 */
export function StockSearch() {
  const router = useRouter();
  const [open, setOpen] = useState(false);

  const close = useCallback(() => setOpen(false), []);
  useStockPickerShortcut(open, setOpen, close);

  return (
    <>
      <Button
        variant="outline"
        onClick={() => setOpen(true)}
        className="justify-start gap-2 text-muted-foreground sm:min-w-56"
      >
        <Search className="size-3.5" aria-hidden />
        <span className="hidden sm:inline">Search stocks…</span>
        <kbd className="ml-auto hidden rounded border bg-muted px-1.5 font-mono text-[10px] sm:inline">
          ⌘K
        </kbd>
      </Button>

      <StockPicker
        open={open}
        onClose={close}
        title="Search stocks"
        onPick={(symbol) => router.push(`/stocks/${symbol}`)}
        hint="Type a ticker or company name. Enter opens the stock; ↑↓ to move."
      />
    </>
  );
}
