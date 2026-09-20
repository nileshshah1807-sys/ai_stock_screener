"use client";

import { useState, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Check, ListPlus, Pencil, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  createWatchlist,
  deleteWatchlist,
  renameWatchlist,
} from "@/app/(app)/watchlists/actions";
import { WATCHLIST_MAX_LISTS, type Watchlist } from "@/lib/types";
import { cn } from "@/lib/utils";

const CHIP =
  "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium " +
  "transition-colors duration-(--duration-fast) ease-(--ease-standard) " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/**
 * Which list is shown, and the controls to manage them.
 *
 * The selection lives in the URL as `?list=<id>`, like every other piece of view
 * state in this app, so a particular list is linkable and survives a reload.
 * Switching lists therefore also resets `page`: page 3 of one list means nothing
 * in another.
 *
 * Renaming and deleting act on the *selected* list only. A control per chip
 * would put a delete button next to every list in a row the reader scans, which
 * is the wrong thing to make easy.
 */
export function WatchlistSelector({
  lists,
  selectedId,
}: {
  lists: Watchlist[];
  selectedId: string | null;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();

  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState("");

  const selected = lists.find((list) => list.id === selectedId) ?? null;

  const select = (id: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("list", id);
    params.delete("page");
    startTransition(() => {
      router.push(`${pathname}?${params.toString()}`, { scroll: false });
    });
  };

  /**
   * Run an action and report the outcome.
   *
   * Server actions here return a result rather than throwing, so a rejected
   * write -- a duplicate name, a full list -- arrives as a message to show
   * rather than an error boundary that loses the page.
   */
  const run = (
    action: (formData: FormData) => Promise<{ ok: boolean; error?: string }>,
    formData: FormData,
    onSuccess?: () => void,
  ) => {
    startTransition(async () => {
      const result = await action(formData);
      if (!result.ok) {
        toast.error(result.error ?? "That did not work.");
        return;
      }
      onSuccess?.();
      router.refresh();
    });
  };

  const submitCreate = () => {
    const name = draft.trim();
    if (!name) return;
    const formData = new FormData();
    formData.set("name", name);
    run(createWatchlist, formData, () => {
      setDraft("");
      setCreating(false);
      toast.success(`Created “${name}”`);
    });
  };

  const submitRename = () => {
    const name = draft.trim();
    if (!name || !selected) return;
    const formData = new FormData();
    formData.set("id", selected.id);
    formData.set("name", name);
    run(renameWatchlist, formData, () => {
      setDraft("");
      setRenaming(false);
      toast.success(`Renamed to “${name}”`);
    });
  };

  const submitDelete = () => {
    if (!selected) return;
    const formData = new FormData();
    formData.set("id", selected.id);
    run(deleteWatchlist, formData, () => {
      toast.success(`Deleted “${selected.name}”`);
      // The selected list no longer exists, so drop it from the URL rather than
      // leaving a link to a deleted id in the address bar.
      const params = new URLSearchParams(searchParams.toString());
      params.delete("list");
      params.delete("page");
      const query = params.toString();
      router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
    });
  };

  const editing = creating || renaming;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {lists.map((list) => {
        const active = list.id === selectedId;
        return (
          <button
            key={list.id}
            type="button"
            aria-pressed={active}
            onClick={() => select(list.id)}
            disabled={pending}
            className={cn(
              CHIP,
              active
                ? "border-primary bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            {list.name}
            {/* The count is the whole reason to glance at this row, so it is on
                the chip rather than only on the selected list. */}
            <span className="tabular font-mono opacity-70">
              {list.symbols.length}
            </span>
          </button>
        );
      })}

      {editing ? (
        <span className="flex items-center gap-1">
          <Input
            autoFocus
            value={draft}
            maxLength={60}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                if (creating) submitCreate();
                else submitRename();
              }
              if (event.key === "Escape") {
                setCreating(false);
                setRenaming(false);
                setDraft("");
              }
            }}
            placeholder={renaming ? "New name…" : "Name the list…"}
            aria-label={renaming ? "New name for the list" : "Name for the new list"}
            className="h-8 w-44 text-xs"
          />
          <Button
            variant="outline"
            className="h-8 px-2"
            disabled={pending || !draft.trim()}
            onClick={creating ? submitCreate : submitRename}
            aria-label="Save"
          >
            <Check className="size-3.5" aria-hidden />
          </Button>
          <Button
            variant="ghost"
            className="h-8 px-2"
            onClick={() => {
              setCreating(false);
              setRenaming(false);
              setDraft("");
            }}
            aria-label="Cancel"
          >
            <X className="size-3.5" aria-hidden />
          </Button>
        </span>
      ) : (
        <>
          {lists.length < WATCHLIST_MAX_LISTS ? (
            <button
              type="button"
              onClick={() => {
                setDraft("");
                setCreating(true);
              }}
              disabled={pending}
              className={cn(
                CHIP,
                "bg-muted text-muted-foreground hover:bg-accent hover:text-foreground",
              )}
            >
              <ListPlus className="size-3.5" aria-hidden />
              New list
            </button>
          ) : null}

          {selected ? (
            <span className="ml-1 flex items-center gap-0.5">
              <Button
                variant="ghost"
                className="h-8 px-2 text-muted-foreground"
                disabled={pending}
                onClick={() => {
                  setDraft(selected.name);
                  setRenaming(true);
                }}
                aria-label={`Rename ${selected.name}`}
                title="Rename this list"
              >
                <Pencil className="size-3.5" aria-hidden />
              </Button>
              <Button
                variant="ghost"
                className="h-8 px-2 text-muted-foreground hover:text-negative"
                disabled={pending}
                onClick={submitDelete}
                aria-label={`Delete ${selected.name}`}
                title={
                  selected.symbols.length
                    ? `Delete this list and its ${selected.symbols.length} symbols`
                    : "Delete this list"
                }
              >
                <Trash2 className="size-3.5" aria-hidden />
              </Button>
            </span>
          ) : null}
        </>
      )}
    </div>
  );
}
