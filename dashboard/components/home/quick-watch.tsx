"use client";

import { createContext, useContext, useState, useTransition } from "react";
import { BookmarkCheck, BookmarkPlus, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { quickAddToWatchlist } from "@/app/(app)/[market]/watchlists/actions";
import { useMarket } from "@/components/market-provider";
import { cn } from "@/lib/utils";

/** The symbols the viewer already watches in this market, so a row shows its state. */
const WatchedContext = createContext<ReadonlySet<string>>(new Set());

export function WatchedProvider({ symbols, children }: { symbols: readonly string[]; children: React.ReactNode }) {
  return <WatchedContext.Provider value={new Set(symbols)}>{children}</WatchedContext.Provider>;
}

/**
 * "+ watchlist" on a stock row: one tap puts the stock on the viewer's first
 * list (made on the spot if they have none). Already watched shows a tick.
 */
export function QuickWatch({ symbol, className }: { symbol: string; className?: string }) {
  const market = useMarket();
  const watched = useContext(WatchedContext).has(symbol);
  const [added, setAdded] = useState(false);
  const [pending, startTransition] = useTransition();
  const done = watched || added;

  const add = () =>
    startTransition(async () => {
      const form = new FormData();
      form.set("market", market.slug);
      form.set("symbol", symbol);
      const result = await quickAddToWatchlist(form);
      if (result.ok) {
        setAdded(true);
      } else {
        toast.error(result.error);
      }
    });

  const Icon = pending ? Loader2 : done ? BookmarkCheck : BookmarkPlus;
  return (
    <button
      type="button"
      onClick={add}
      disabled={pending || done}
      aria-label={done ? `${symbol} is on your watchlist` : `Add ${symbol} to your watchlist`}
      title={done ? "On your watchlist" : "Add to watchlist"}
      className={cn(
        "inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground sm:size-7",
        "hover:bg-muted hover:text-foreground disabled:hover:bg-transparent",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        done && "text-positive",
        className,
      )}
    >
      <Icon className={cn("size-4", pending && "animate-spin")} aria-hidden />
    </button>
  );
}
