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
import { Bookmark, BookmarkPlus, ChevronDown, Link2, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { SAVED_VIEWS_MAX, unsentViews } from "@/lib/saved-views.mjs";
import { groupViews, viewsButtonLabel } from "@/lib/view-groups.mjs";

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
    // Beyond the cap stays in the browser and moves on a later visit.
    const legacy = savedViewsSnapshot().slice(0, SAVED_VIEWS_MAX);
    loadSavedViews(market.code, legacy)
      .then((result) => {
        if (!live || !result.ok) return;
        // Moved into the account (or already there by name): what was sent
        // leaves the browser, and nothing saved since.
        if (legacy.length) writeSavedViews(unsentViews(savedViewsSnapshot(), legacy));
        if (result.notMoved) {
          toast.warning(
            `${result.notMoved} saved ${result.notMoved === 1 ? "view was" : "views were"} not kept: your account holds ${SAVED_VIEWS_MAX} per market.`,
          );
        }
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
        className="w-44"
      />
      <Button variant="outline" onClick={saveCurrent}>
        Save
      </Button>
    </span>
  ) : null;

  const grouped = groupViews(presets);
  const activeLabels = [...presets, ...saved]
    .filter((view) => viewIsActive(searchParams, view.query))
    .map((view) => view.label);

  return (
    <>
      <PendingMarker pending={pending} />
      {/*
        One button beside Filters and Your score rather than a row of chips: twelve equal pills
        wrapped to two rows (four at the pane's default width) and read as noise. The menu groups
        the views, states each one's rule, and stays open so views can be combined; the active
        filter chips beside the grid say what is applied.
      */}
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="outline"
              className="relative max-w-[16rem] gap-1.5 max-sm:size-9 max-sm:px-0"
              aria-label={activeLabels.length ? `Views, on: ${activeLabels.join(", ")}` : "Views"}
            />
          }
        >
          <Bookmark className="size-3.5 shrink-0" aria-hidden />
          <span className="hidden truncate sm:inline">{viewsButtonLabel(activeLabels)}</span>
          {activeLabels.length ? (
            <span
              className={cn(
                "tabular ml-0.5 rounded-full bg-primary px-1.5 text-[10px] font-semibold text-primary-foreground",
                "max-sm:absolute max-sm:-top-1 max-sm:-right-1 max-sm:ml-0 max-sm:min-w-4 max-sm:leading-4",
                activeLabels.length === 1 && "sm:hidden",
              )}
            >
              {activeLabels.length}
            </span>
          ) : null}
          <ChevronDown className="hidden size-3 shrink-0 opacity-60 sm:block" aria-hidden />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="max-h-[min(var(--available-height),34rem)] w-80">
          {grouped.map(({ group, views }, at) => (
            <DropdownMenuGroup key={group}>
              {at ? <DropdownMenuSeparator /> : null}
              <DropdownMenuLabel>{group}</DropdownMenuLabel>
              {views.map((preset) => (
                <DropdownMenuCheckboxItem
                  key={preset.id}
                  checked={viewIsActive(searchParams, preset.query)}
                  onCheckedChange={() => apply(preset.query)}
                  className="items-start py-2"
                >
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span>{preset.label}</span>
                    <span className="line-clamp-2 text-xs text-muted-foreground">{preset.description}</span>
                  </span>
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuGroup>
          ))}
          {saved.length ? (
            <DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuLabel>Saved</DropdownMenuLabel>
              {saved.map((view) => (
                <DropdownMenuCheckboxItem
                  key={view.id}
                  checked={viewIsActive(searchParams, view.query)}
                  onCheckedChange={() => apply(view.query)}
                >
                  <span className="truncate">{view.label}</span>
                </DropdownMenuCheckboxItem>
              ))}
              <DropdownMenuSub>
                <DropdownMenuSubTrigger>
                  <Trash2 aria-hidden />
                  Delete a saved view
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent className="w-56">
                  {saved.map((view) => (
                    <DropdownMenuItem key={view.id} onClick={() => remove(view)}>
                      <span className="truncate">{view.label}</span>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuSubContent>
              </DropdownMenuSub>
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
    </>
  );
}
