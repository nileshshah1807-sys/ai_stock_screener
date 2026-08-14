"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";

import { RatingBadge } from "@/components/rating-badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { SearchEntry } from "@/lib/types";

const MAX_RESULTS = 8;

/**
 * Ranked match over the pre-shipped universe index.
 *
 * Ordering is deliberate: someone typing "INF" wants INFY, not the first
 * company whose name happens to contain "inf". Exact ticker beats ticker
 * prefix, which beats a word-start in the company name, which beats any
 * substring. Within a tier the better-ranked stock wins.
 */
function rank(entries: SearchEntry[], term: string): SearchEntry[] {
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
    else if (new RegExp(`\\b${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(company))
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
 * page load, no matter how often the dialog is opened and closed.
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

export function StockSearch() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [cursor, setCursor] = useState(0);
  const [entries, setEntries] = useState<SearchEntry[]>([]);
  const [status, setStatus] = useState<"idle" | "ready">("idle");
  const inputRef = useRef<HTMLInputElement>(null);

  const results = useMemo(() => rank(entries, term), [entries, term]);

  // Derived rather than its own state: setting a loading flag synchronously in
  // the effect below would cascade an extra render on every open.
  const loading = open && status === "idle";

  const close = useCallback(() => {
    setOpen(false);
    setTerm("");
    setCursor(0);
  }, []);

  // Fetched on first open rather than with the page: the index is ~180 KB and
  // most visits never open the search dialog at all. loadIndex() dedupes at
  // module scope, so a double-invoked effect still makes one request.
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
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (open) {
          close();
        } else {
          setOpen(true);
        }
      }
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [close, open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const go = (symbol: string) => {
    close();
    router.push(`/stocks/${symbol}`);
  };

  const onInputKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((value) => Math.min(value + 1, results.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((value) => Math.max(value - 1, 0));
    } else if (event.key === "Enter" && results[cursor]) {
      event.preventDefault();
      go(results[cursor].s);
    }
  };

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

      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-[12vh]"
          onClick={close}
          role="presentation"
        >
          <div
            className="w-full max-w-lg overflow-hidden rounded-xl border bg-popover shadow-2xl"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="Search stocks"
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
                placeholder="Symbol or company name…"
                aria-label="Search stocks"
                aria-autocomplete="list"
                aria-controls="stock-search-results"
                className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              />
              <span className="tabular shrink-0 font-mono text-[11px] text-muted-foreground">
                {loading
                  ? "loading…"
                  : `${entries.length.toLocaleString("en-IN")} stocks`}
              </span>
            </div>

            <ul id="stock-search-results" role="listbox" className="max-h-80 overflow-y-auto p-1">
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

              {results.map((entry, index) => (
                <li key={entry.s}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={index === cursor}
                    onMouseEnter={() => setCursor(index)}
                    onClick={() => go(entry.s)}
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
                  </button>
                </li>
              ))}

              {!term && !loading ? (
                <li className="px-3 py-6 text-center text-xs text-muted-foreground">
                  Type a ticker or company name. Enter opens the stock; ↑↓ to
                  move.
                </li>
              ) : null}
            </ul>
          </div>
        </div>
      ) : null}
    </>
  );
}
