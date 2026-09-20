"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { Loader2, X } from "lucide-react";
import { toast } from "sonner";

import { removeFromWatchlist } from "@/app/(app)/watchlists/actions";
import { cn } from "@/lib/utils";

/**
 * Remove one symbol from the list being shown.
 *
 * A client component rather than a bare `<form action={...}>` so a rejected
 * write can say why. A list is capped at 200 symbols and usually holds a few
 * dozen, so the per-row cost of this is not the concern it would be in the
 * screener grid's 100 rows.
 *
 * No confirmation step. Removing a symbol from a watchlist is one click to undo
 * -- the add control is on the row it came from and on the stock page -- so a
 * dialog would cost more than the mistake does.
 */
export function WatchlistRowAction({
  watchlistId,
  symbol,
}: {
  watchlistId: string;
  symbol: string;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  const remove = () => {
    startTransition(async () => {
      const formData = new FormData();
      formData.set("watchlistId", watchlistId);
      formData.set("symbol", symbol);
      const result = await removeFromWatchlist(formData);
      if (!result.ok) {
        toast.error(result.error);
        return;
      }
      toast.success(`Removed ${symbol}`);
      router.refresh();
    });
  };

  return (
    <button
      type="button"
      onClick={remove}
      disabled={pending}
      aria-label={`Remove ${symbol} from this watchlist`}
      title="Remove from this watchlist"
      className={cn(
        "inline-flex size-6 items-center justify-center rounded-full",
        "text-muted-foreground transition-colors duration-(--duration-fast)",
        "hover:bg-muted hover:text-negative",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        pending && "opacity-60",
      )}
    >
      {pending ? (
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
      ) : (
        <X className="size-3.5" aria-hidden />
      )}
    </button>
  );
}
