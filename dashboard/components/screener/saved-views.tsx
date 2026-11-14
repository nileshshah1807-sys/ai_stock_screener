"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  useTransition,
} from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { BookmarkPlus, Check, ChevronDown, Link2, Star, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  applyView,
  removeView,
  currentViewQuery,
  PRESETS,
  savedViewsServerSnapshot,
  savedViewsSnapshot,
  subscribeSavedViews,
  viewIsActive,
  writeSavedViews,
  type SavedView,
} from "@/lib/presets";
import { PendingMarker } from "@/components/nav-pending";
import { cn } from "@/lib/utils";
import { useMarket, useShowRatings } from "@/components/market-provider";
import { usesRatingFilter, usesVerdict } from "@/lib/ratings.mjs";
import { deleteView, loadSavedViews, saveView } from "@/app/(app)/[market]/screener/actions";

const CHIP =
  "inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-xs font-medium " +
  "transition-colors duration-(--duration-fast) ease-(--ease-standard) " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

const CHIP_ACTIVE = "border-primary bg-primary text-primary-foreground";
const CHIP_IDLE =
  "bg-muted text-muted-foreground hover:bg-accent hover:text-foreground";

/**
 * Named views: built-in presets, then whatever the reader saved.
 *
 * A view is a query string, so this component stores nothing but a label. The
 * built-ins live in `lib/presets.ts`; user views live in the viewer's account
 * (`saved_views`, read after hydration so the page's render pays nothing), so
 * they follow them to another device. Browser storage is the fallback until
 * that table exists, and its views move into the account on the first load
 * after it does.
 *
 * The copy-link button is here rather than beside Export because it is the same
 * idea as a saved view: `lib/filters.ts` says shareability is the point of
 * keeping every filter in the URL, and until now nothing in the UI said so.
 */
export function SavedViews({ factorModel = false }: { factorModel?: boolean }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const market = useMarket();
  const showRatings = useShowRatings();
  const [pending, startTransition] = useTransition();

  // localStorage does not exist on the server, so the server snapshot is empty
  // and React reconciles to the real list after hydration. Going through the
  // store rather than an effect also means a view saved in another tab appears
  // here without a reload.
  const local = useSyncExternalStore(
    subscribeSavedViews,
    savedViewsSnapshot,
    savedViewsServerSnapshot,
  );
  // null until the account answers, and for good when it cannot (signed out,
  // table not applied): the browser's list stands in.
  const [account, setAccount] = useState<SavedView[] | null>(null);
  const saved = account ?? local;

  useEffect(() => {
    let live = true;
    const legacy = savedViewsSnapshot();
    loadSavedViews(market.code, legacy)
      .then((result) => {
        if (!live || !result.ok) return;
        // Moved into the account (or already there by name): the browser copy goes.
        if (legacy.length) writeSavedViews([]);
        setAccount(result.views);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [market.code]);
  const [naming, setNaming] = useState(false);
  const [draftName, setDraftName] = useState("");

  const presets = useMemo(
    () =>
      PRESETS.filter(
        (preset) =>
          (factorModel || !preset.factorOnly) &&
          (!preset.market || preset.market === market.code) &&
          !usesVerdict(preset.query) &&
          (showRatings || !usesRatingFilter(preset.query)),
      ),
    [factorModel, market.code, showRatings],
  );

  const apply = useCallback(
    (query: string) => {
      // A lit view's chip takes it off again; any other adds it to what is on.
      const current = new URLSearchParams(searchParams.toString());
      const next = viewIsActive(searchParams, query) ? removeView(current, query) : applyView(current, query);
      startTransition(() => {
        router.push(
          next.toString() ? `${pathname}?${next.toString()}` : pathname,
          { scroll: false },
        );
      });
    },
    [pathname, router, searchParams],
  );

  const remove = (view: SavedView) => {
    if (!account) {
      writeSavedViews(local.filter((item) => item.id !== view.id));
      return;
    }
    if (view.id.startsWith("pending-")) return; // its save has not answered yet
    const before = account;
    setAccount(before.filter((item) => item.id !== view.id));
    deleteView(market.code, view.id).then((result) => {
      if (result.ok) return;
      setAccount(before);
      toast.error(result.error || "Could not delete the view.");
    });
  };

  const store = (label: string, query: string) => {
    if (!account) {
      // Same name overwrites rather than accumulating near-duplicates, which is
      // what "save" means everywhere else.
      const existing = local.filter((view) => view.label.toLowerCase() !== label.toLowerCase());
      writeSavedViews([...existing, { id: `${Date.now()}`, label, query }]);
      return;
    }
    const before = account;
    const pendingId = `pending-${Date.now()}`;
    const same = before.findIndex((view) => view.label.toLowerCase() === label.toLowerCase());
    setAccount(
      same >= 0
        ? before.map((view, at) => (at === same ? { ...view, label, query } : view))
        : [...before, { id: pendingId, label, query }],
    );
    saveView(market.code, label, query).then((result) => {
      if (!result.ok) {
        setAccount(before);
        toast.error(result.error || "Could not save the view.");
        return;
      }
      setAccount((views) =>
        views?.map((view) =>
          view.id === pendingId || view.id === result.view.id ? result.view : view,
        ) ?? views,
      );
    });
  };

  const saveCurrent = () => {
    const label = draftName.trim();
    if (!label) return;
    const query = currentViewQuery(searchParams);
    if (!query) {
      toast.error("Nothing to save", {
        description: "Set at least one filter, sort or column first.",
      });
      return;
    }
    store(label, query);
    setDraftName("");
    setNaming(false);
    toast.success(`Saved “${label}”`);
  };

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      toast.success("Link copied", {
        description: "It carries the filters, sort and columns you can see.",
      });
    } catch {
      // Clipboard access is refused outside a secure context and in some
      // embedded browsers. Say so instead of failing silently.
      toast.error("Could not copy", {
        description: "Copy the address bar instead.",
      });
    }
  };

  const nameInput = naming ? (
    <span className="flex items-center gap-1">
      <Input
        autoFocus
        value={draftName}
        onChange={(event) => setDraftName(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") saveCurrent();
          if (event.key === "Escape") {
            setNaming(false);
            setDraftName("");
          }
        }}
        placeholder="Name this view…"
        aria-label="Name for the saved view"
        className="h-8 w-40 text-xs"
      />
      <Button variant="outline" className="h-8 px-2.5 text-xs" onClick={saveCurrent}>
        Save
      </Button>
    </span>
  ) : null;

  const activeView =
    presets.find((preset) => viewIsActive(searchParams, preset.query)) ??
    saved.find((view) => viewIsActive(searchParams, view.query));

  return (
    <>
      <PendingMarker pending={pending} />
      {/*
        Phone: one menu instead of a wrapping row of chips. Five presets plus
        Save and Copy link took three rows above the grid; the trigger names the
        active view, so what is applied is still visible at a glance.
      */}
      <div className="flex items-center gap-1.5 sm:hidden">
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <button
                type="button"
                className={cn(CHIP, activeView ? CHIP_ACTIVE : CHIP_IDLE, "max-w-[14rem]")}
              />
            }
          >
            <Star className="size-3 shrink-0" aria-hidden />
            <span className="truncate">{activeView ? activeView.label : "Views"}</span>
            <ChevronDown className="size-3 shrink-0 opacity-70" aria-hidden />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-64">
            <DropdownMenuGroup>
              <DropdownMenuLabel>Views</DropdownMenuLabel>
              {presets.map((preset) => (
                <DropdownMenuItem key={preset.id} onClick={() => apply(preset.query)}>
                  <span className="flex-1">{preset.label}</span>
                  {viewIsActive(searchParams, preset.query) ? (
                    <Check className="size-3.5" aria-hidden />
                  ) : null}
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
            {saved.length ? (
              <DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuLabel>Saved</DropdownMenuLabel>
                {saved.map((view) => (
                  <DropdownMenuItem key={view.id} onClick={() => apply(view.query)}>
                    <span className="flex-1 truncate">{view.label}</span>
                    {viewIsActive(searchParams, view.query) ? (
                      <Check className="size-3.5" aria-hidden />
                    ) : null}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuGroup>
            ) : null}
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => setNaming(true)}>
              <BookmarkPlus aria-hidden />
              Save current view
            </DropdownMenuItem>
            <DropdownMenuItem onClick={copyLink}>
              <Link2 aria-hidden />
              Copy link
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        {nameInput}
      </div>

    <div className="hidden flex-wrap items-center gap-1.5 sm:flex">
      <span className="mr-0.5 flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <Star className="size-3" aria-hidden />
        Views
      </span>

      {presets.map((preset) => {
        const active = viewIsActive(searchParams, preset.query);
        return (
          <Tooltip key={preset.id}>
            <TooltipTrigger
              render={
                <button
                  type="button"
                  aria-pressed={active}
                  onClick={() => apply(preset.query)}
                  className={cn(CHIP, active ? CHIP_ACTIVE : CHIP_IDLE)}
                />
              }
            >
              {preset.label}
            </TooltipTrigger>
            <TooltipContent className="max-w-72">
              <p className="text-xs">{preset.description}</p>
            </TooltipContent>
          </Tooltip>
        );
      })}

      {saved.map((view) => {
        const active = viewIsActive(searchParams, view.query);
        return (
          <span
            key={view.id}
            className={cn(
              CHIP,
              "pr-1",
              active ? CHIP_ACTIVE : CHIP_IDLE,
            )}
          >
            <button
              type="button"
              aria-pressed={active}
              onClick={() => apply(view.query)}
              className="rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {view.label}
            </button>
            <button
              type="button"
              aria-label={`Delete saved view ${view.label}`}
              onClick={() => remove(view)}
              className="rounded-md p-0.5 opacity-60 transition-opacity hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Trash2 className="size-3" aria-hidden />
            </button>
          </span>
        );
      })}

      {naming ? (
        nameInput
      ) : (
        <button type="button" onClick={() => setNaming(true)} className={cn(CHIP, CHIP_IDLE)}>
          <BookmarkPlus className="size-3" aria-hidden />
          Save current
        </button>
      )}

      <button type="button" onClick={copyLink} className={cn(CHIP, CHIP_IDLE)}>
        <Link2 className="size-3" aria-hidden />
        Copy link
      </button>
    </div>
    </>
  );
}
