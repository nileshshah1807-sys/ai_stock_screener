"use client";

import { useCallback, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  StockPicker,
  useStockPickerShortcut,
} from "@/components/screener/stock-picker";
import {
  addToWatchlist,
  removeFromWatchlist,
} from "@/app/(app)/watchlists/actions";

/**
 * Add stocks to the selected list, by ticker or company name.
 *
 * Same dialog as the screener's Cmd+K search -- same index, same ranking, same
 * keyboard handling -- with a different verb. Only one picker is mounted per
 * route, so the shortcut binding does not collide: the screener's lives in its
 * layout, this one on the watchlist page.
 *
 * Three behaviours that differ from the search version, all for adding several
 * names in one sitting:
 *
 *  * The dialog stays open after a pick and clears the term, so five additions
 *    are five type-and-enters rather than five reopenings.
 *  * Symbols already on the list carry a tick, and picking one *removes* it. The
 *    control is symmetric, so a mistyped add is undone where it was made.
 *  * The grid is refreshed once on close rather than after every pick. Repainting
 *    100 rows under a dialog that is still open is work nobody sees, and it makes
 *    the next keystroke feel slow.
 */
export function WatchlistSearch({
  watchlistId,
  watchlistName,
  present,
}: {
  watchlistId: string;
  watchlistName: string;
  /** Symbols currently on the list, from the server. */
  present: readonly string[];
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  const [busySymbol, setBusySymbol] = useState<string | null>(null);

  // Mirrors server state so a tick appears on the click rather than after the
  // round trip. Seeded from the server on every render of the parent, so it
  // re-syncs when the refresh lands.
  const [marked, setMarked] = useState<Set<string>>(() => new Set(present));
  const [dirty, setDirty] = useState(false);

  const close = useCallback(() => {
    setOpen(false);
    // One refresh for the whole session of additions.
    if (dirty) {
      setDirty(false);
      router.refresh();
    }
  }, [dirty, router]);

  useStockPickerShortcut(open, setOpen, close);

  const toggle = (symbol: string) => {
    const isMember = marked.has(symbol);

    setBusySymbol(symbol);
    setMarked((current) => {
      const next = new Set(current);
      if (isMember) next.delete(symbol);
      else next.add(symbol);
      return next;
    });

    startTransition(async () => {
      const formData = new FormData();
      formData.set("watchlistId", watchlistId);
      formData.set("symbol", symbol);
      const result = await (isMember
        ? removeFromWatchlist(formData)
        : addToWatchlist(formData));
      setBusySymbol(null);

      if (!result.ok) {
        // Put the tick back where it was. A full list and a duplicate name both
        // arrive here, and both need the checkbox to tell the truth again.
        setMarked((current) => {
          const next = new Set(current);
          if (isMember) next.add(symbol);
          else next.delete(symbol);
          return next;
        });
        toast.error(result.error);
        return;
      }

      setDirty(true);
      toast.success(
        isMember
          ? `Removed ${symbol} from “${watchlistName}”`
          : `Added ${symbol} to “${watchlistName}”`,
      );
    });
  };

  return (
    <>
      <Button
        variant="outline"
        onClick={() => setOpen(true)}
        disabled={pending && !open}
        className="justify-start gap-2 text-muted-foreground sm:min-w-56"
      >
        <Plus className="size-3.5" aria-hidden />
        <span className="hidden sm:inline">Add stocks…</span>
        <kbd className="ml-auto hidden rounded border bg-muted px-1.5 font-mono text-[10px] sm:inline">
          ⌘K
        </kbd>
      </Button>

      <StockPicker
        open={open}
        onClose={close}
        title={`Add stocks to ${watchlistName}`}
        placeholder="Symbol or company name…"
        onPick={toggle}
        marked={marked}
        busySymbol={busySymbol}
        stayOpen
        hint={`Type a ticker or company name. Enter adds it to “${watchlistName}”; a ticked name is already on the list and Enter removes it.`}
      />
    </>
  );
}
