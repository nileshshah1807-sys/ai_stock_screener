"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { BookmarkCheck, BookmarkPlus, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  addToWatchlist,
  createWatchlist,
  removeFromWatchlist,
} from "@/app/(app)/watchlists/actions";
import { WATCHLIST_MAX_LISTS, type Watchlist } from "@/lib/types";

/**
 * Put a symbol on one or more lists, from the stock page.
 *
 * Checkboxes rather than an "add" button, because membership is the state being
 * edited and a symbol can be on several lists at once. Unchecking removes, so
 * the control is symmetric and the reader does not have to go to the watchlist
 * page to undo an add.
 *
 * The list of lists is passed in from the server rather than fetched here: the
 * page already reads it to render this component's initial checked state, and a
 * second client fetch would only add a spinner.
 */
export function AddToWatchlist({
  symbol,
  lists,
  memberOf,
}: {
  symbol: string;
  lists: Watchlist[];
  /** Ids of the lists that already contain this symbol. */
  memberOf: string[];
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState("");

  // Server state is the source of truth; this mirrors it so a checkbox responds
  // to the click rather than to the round trip. Reconciled from the refresh.
  const [checked, setChecked] = useState<Set<string>>(new Set(memberOf));

  const toggle = (list: Watchlist) => {
    const isMember = checked.has(list.id);
    // Optimistic, then reverted on failure. The alternative -- waiting for the
    // server -- makes a checkbox feel broken at ~200ms of latency.
    setChecked((current) => {
      const next = new Set(current);
      if (isMember) next.delete(list.id);
      else next.add(list.id);
      return next;
    });

    startTransition(async () => {
      const formData = new FormData();
      formData.set("watchlistId", list.id);
      formData.set("symbol", symbol);
      const result = await (isMember
        ? removeFromWatchlist(formData)
        : addToWatchlist(formData));

      if (!result.ok) {
        setChecked((current) => {
          const next = new Set(current);
          if (isMember) next.add(list.id);
          else next.delete(list.id);
          return next;
        });
        toast.error(result.error);
        return;
      }
      router.refresh();
    });
  };

  const submitCreate = () => {
    const name = draft.trim();
    if (!name) return;
    startTransition(async () => {
      const created = new FormData();
      created.set("name", name);
      const result = await createWatchlist(created);
      if (!result.ok) {
        toast.error(result.error);
        return;
      }
      setDraft("");
      setCreating(false);
      toast.success(`Created “${name}”`, {
        description: `Tick it to add ${symbol}.`,
      });
      router.refresh();
    });
  };

  const count = checked.size;

  return (
    <Popover>
      <PopoverTrigger render={<Button variant="outline" className="gap-1.5" />}>
        {pending ? (
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
        ) : count ? (
          <BookmarkCheck className="size-3.5" aria-hidden />
        ) : (
          <BookmarkPlus className="size-3.5" aria-hidden />
        )}
        {count ? `On ${count} list${count > 1 ? "s" : ""}` : "Watch"}
      </PopoverTrigger>

      <PopoverContent align="end" className="w-72">
        <div className="space-y-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Watchlists
          </p>

          {lists.length ? (
            <div className="max-h-56 space-y-1.5 overflow-y-auto pr-1">
              {lists.map((list) => (
                <div key={list.id} className="flex items-center gap-2">
                  <Checkbox
                    id={`watch-${list.id}`}
                    checked={checked.has(list.id)}
                    onCheckedChange={() => toggle(list)}
                  />
                  <Label
                    htmlFor={`watch-${list.id}`}
                    className="flex min-w-0 flex-1 cursor-pointer items-baseline gap-1.5 text-sm font-normal"
                  >
                    <span className="truncate">{list.name}</span>
                    <span className="tabular ml-auto shrink-0 font-mono text-[11px] text-muted-foreground">
                      {list.symbols.length}
                    </span>
                  </Label>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No lists yet. Create one to start tracking {symbol}.
            </p>
          )}

          {creating ? (
            <div className="flex items-center gap-1">
              <Input
                autoFocus
                value={draft}
                maxLength={60}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    submitCreate();
                  }
                  if (event.key === "Escape") {
                    setCreating(false);
                    setDraft("");
                  }
                }}
                placeholder="Name the list…"
                aria-label="Name for the new watchlist"
                className="h-8 text-xs"
              />
              <Button
                variant="outline"
                className="h-8 px-2.5 text-xs"
                disabled={pending || !draft.trim()}
                onClick={submitCreate}
              >
                Add
              </Button>
            </div>
          ) : lists.length < WATCHLIST_MAX_LISTS ? (
            <Button
              variant="ghost"
              className="h-8 w-full justify-start gap-1.5 px-2 text-xs"
              onClick={() => setCreating(true)}
            >
              <BookmarkPlus className="size-3.5" aria-hidden />
              New list
            </Button>
          ) : null}
        </div>
      </PopoverContent>
    </Popover>
  );
}
