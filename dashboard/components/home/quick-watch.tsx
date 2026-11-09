"use client";

import { createContext, useContext, useState, useTransition } from "react";
import { BookmarkCheck, BookmarkPlus, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { quickAddToWatchlist, quickRemoveFromWatchlist } from "@/app/(app)/[market]/watchlists/actions";
import { useMarket } from "@/components/market-provider";
import { cn } from "@/lib/utils";

/** The symbols the viewer already watches in this market, so a row shows its state. */
const WatchedContext = createContext<ReadonlySet<string>>(new Set());

export function WatchedProvider({ symbols, children }: { symbols: readonly string[]; children: React.ReactNode }) {
  return <WatchedContext.Provider value={new Set(symbols)}>{children}</WatchedContext.Provider>;
}

/**
 * "+ watchlist" on a stock row: one tap puts the stock on the viewer's first
 * list (made on the spot if they have none); a second tap takes it off every
 * list. Already watched shows a tick.
 */
export function QuickWatch({ symbol, className }: { symbol: string; className?: string }) {
  const market = useMarket();
  const initial = useContext(WatchedContext).has(symbol);
  // What this tap last did; until then, what the server said.
  const [on, setOn] = useState<boolean | null>(null);
  const [pending, startTransition] = useTransition();
  const done = on ?? initial;

  const toggle = () =>
    startTransition(async () => {
      const form = new FormData();
      form.set("market", market.slug);
      form.set("symbol", symbol);
      const result = await (done ? quickRemoveFromWatchlist(form) : quickAddToWatchlist(form));
      if (result.ok) {
        setOn(!done);
      } else {
        toast.error(result.error);
      }
    });

  const Icon = pending ? Loader2 : done ? BookmarkCheck : BookmarkPlus;
  return (
    <button
      type="button"
      onClick={toggle}
      disabled={pending}
      aria-label={done ? `Remove ${symbol} from your watchlist` : `Add ${symbol} to your watchlist`}
      title={done ? "On your watchlist: tap to remove" : "Add to watchlist"}
      className={cn(
        "inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground sm:size-7",
        "hover:bg-muted hover:text-foreground",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        done && "text-positive",
        className,
      )}
    >
      <Icon className={cn("size-4", pending && "animate-spin")} aria-hidden />
    </button>
  );
}
