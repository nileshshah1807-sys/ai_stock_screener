"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, Loader2, Search } from "lucide-react";

import { RatingBadge } from "@/components/rating-badge";
import { cn } from "@/lib/utils";
import type { SearchEntry } from "@/lib/types";

const MAX_RESULTS = 8;

/**
 * The universe typeahead, without an opinion about what picking does.
 *
 * Extracted from StockSearch so the watchlist page can add a symbol with the
 * same control that the screener uses to navigate to one. The ranking, the index
 * fetch, the keyboard handling and the dialog chrome are all here; the caller
 * supplies the trigger and the verb.
 *
 * Callers own their own trigger button because the labels differ ("Search
 * stocks" versus "Add stocks"), and they own their own shortcut binding through
 * `useStockPickerShortcut`.
 */

/**
 * Ranked match over the pre-shipped universe index.
 *
 * Ordering is deliberate: someone typing "INF" wants INFY, not the first
 * company whose name happens to contain "inf". Exact ticker beats ticker
 * prefix, which beats a word-start in the company name, which beats any
 * substring. Within a tier the better-ranked stock wins.
 */
export function rank(entries: SearchEntry[], term: string): SearchEntry[] {
  const query = term.trim().toUpperCase();
  if (!query) return [];

  const scored: Array<{ entry: SearchEntry; tier: number }> = [];

  for (const entry of entries) {
    const symbol = entry.s.toUpperCase();
    const company = entry.c.toUpperCase();

    let tier = -1;
    if (symbol === query) tier = 0;
    else if (symbol.startsWith(query)) tier = 1;
    else if (company.startsWith(query)) tier = 2;
    else if (
      new RegExp(`\\b${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(company)
    )
      tier = 3;
    else if (symbol.includes(query) || company.includes(query)) tier = 4;

    if (tier >= 0) scored.push({ entry, tier });
  }

  scored.sort((a, b) => {
    if (a.tier !== b.tier) return a.tier - b.tier;
    return (a.entry.r ?? 1e9) - (b.entry.r ?? 1e9);
  });

  return scored.slice(0, MAX_RESULTS).map((item) => item.entry);
}

/**
 * Module-scoped so the index survives remounts and is fetched at most once per
 * page load, no matter how often the dialog is opened and closed -- and now, no
 * matter which of the two pickers opens it.
 */
let indexPromise: Promise<SearchEntry[]> | null = null;

function loadIndex(): Promise<SearchEntry[]> {
  indexPromise ??= fetch("/api/search-index")
    .then((response) => (response.ok ? response.json() : { entries: [] }))
    .then((payload) => (payload.entries ?? []) as SearchEntry[])
    .catch(() => {
      // Let a failed load retry the next time the dialog opens rather than
      // caching the failure for the life of the page.
      indexPromise = null;
      return [];
    });
  return indexPromise;
}

/**
 * Bind Cmd/Ctrl+K and Escape.
 *
 * A hook rather than part of the dialog because the shortcut has to work when
 * the dialog is closed, and only one picker is ever mounted per route -- the
 * screener's lives in its layout, the watchlist's on its page -- so the two
 * cannot fight over the binding.
 */
export function useStockPickerShortcut(
  open: boolean,
  setOpen: (next: boolean) => void,
  close: () => void,
): void {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (open) close();
        else setOpen(true);
      }
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [close, open, setOpen]);
}

export function StockPicker({
  open,
  onClose,
  onPick,
  placeholder = "Symbol or company name…",
  hint,
  title,
  /** Symbols already accounted for, rendered with a tick. */
  marked,
  /** Symbol currently being written, rendered with a spinner. */
  busySymbol,
  /** Keep the dialog open after a pick, for adding several in a row. */
  stayOpen = false,
}: {
  open: boolean;
  onClose: () => void;
  onPick: (symbol: string) => void;
  placeholder?: string;
  hint?: string;
  title: string;
  marked?: ReadonlySet<string>;
  busySymbol?: string | null;
  stayOpen?: boolean;
}) {
  const [term, setTerm] = useState("");
  const [cursor, setCursor] = useState(0);
  const [entries, setEntries] = useState<SearchEntry[]>([]);
  const [status, setStatus] = useState<"idle" | "ready">("idle");
  const inputRef = useRef<HTMLInputElement>(null);

  const results = useMemo(() => rank(entries, term), [entries, term]);

  // Derived rather than its own state: setting a loading flag synchronously in
  // the effect below would cascade an extra render on every open.
  const loading = open && status === "idle";

  // Fetched on first open rather than with the page: the index is ~180 KB and
  // most visits never open the dialog at all. loadIndex() dedupes at module
  // scope, so a double-invoked effect still makes one request.
  useEffect(() => {
    if (!open || status === "ready") return;
    let active = true;
    loadIndex().then((loaded) => {
      if (!active) return;
      setEntries(loaded);
      setStatus("ready");
    });
    return () => {
      active = false;
    };
  }, [open, status]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const pick = useCallback(
    (symbol: string) => {
      onPick(symbol);
      if (stayOpen) {
        // Clear the term but keep focus, so adding five names is five
        // type-and-enters rather than five reopenings of the dialog.
        setTerm("");
        setCursor(0);
        inputRef.current?.focus();
      } else {
        onClose();
      }
    },
    [onClose, onPick, stayOpen],
  );

  const onInputKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((value) => Math.min(value + 1, results.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((value) => Math.max(value - 1, 0));
    } else if (event.key === "Enter" && results[cursor]) {
      event.preventDefault();
      pick(results[cursor].s);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-[12vh]"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-xl border bg-popover shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="flex items-center gap-2 border-b px-3">
          <Search className="size-4 text-muted-foreground" aria-hidden />
          <input
            ref={inputRef}
            value={term}
            onChange={(event) => {
              setTerm(event.target.value);
              setCursor(0);
            }}
            onKeyDown={onInputKeyDown}
            placeholder={placeholder}
            aria-label={title}
            aria-autocomplete="list"
            aria-controls="stock-picker-results"
            className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          <span className="tabular shrink-0 font-mono text-[11px] text-muted-foreground">
            {loading
              ? "loading…"
              : `${entries.length.toLocaleString("en-IN")} stocks`}
          </span>
        </div>

        <ul
          id="stock-picker-results"
          role="listbox"
          className="max-h-80 overflow-y-auto p-1"
        >
          {term && !results.length && !loading ? (
            <li className="px-3 py-6 text-center text-sm text-muted-foreground">
              No match for “{term}”.
            </li>
          ) : null}

          {loading ? (
            <li
              aria-live="polite"
              className="px-3 py-6 text-center text-sm text-muted-foreground"
            >
              Loading stocks…
            </li>
          ) : null}

          {results.map((entry, index) => {
            const isMarked = marked?.has(entry.s) ?? false;
            const isBusy = busySymbol === entry.s;
            return (
              <li key={entry.s}>
                <button
                  type="button"
                  role="option"
                  aria-selected={index === cursor}
                  onMouseEnter={() => setCursor(index)}
                  onClick={() => pick(entry.s)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left",
                    index === cursor ? "bg-accent" : "hover:bg-muted",
                  )}
                >
                  <span className="tabular w-9 shrink-0 font-mono text-xs text-muted-foreground">
                    {entry.r ?? "—"}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-mono text-sm font-medium">
                      {entry.s}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {entry.c}
                    </span>
                  </span>
                  <span className="tabular shrink-0 font-mono text-xs">
                    {entry.d?.toFixed(1) ?? "—"}
                  </span>
                  <RatingBadge rating={entry.g} />
                  {/* Fixed-width slot whether or not a glyph is in it, so the
                      rating badges above and below stay on one vertical line as
                      the marked state changes. */}
                  <span className="flex size-4 shrink-0 items-center justify-center">
                    {isBusy ? (
                      <Loader2
                        className="size-3.5 animate-spin text-muted-foreground"
                        aria-hidden
                      />
                    ) : isMarked ? (
                      <Check className="size-3.5 text-positive" aria-hidden />
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}

          {!term && !loading ? (
            <li className="px-3 py-6 text-center text-xs text-muted-foreground">
              {hint ?? "Type a ticker or company name. ↑↓ to move."}
            </li>
          ) : null}
        </ul>
      </div>
    </div>
  );
}
