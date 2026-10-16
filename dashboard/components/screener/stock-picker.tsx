"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChartLine, ChevronRight, Loader2, Search } from "lucide-react";

import { RatingBadge } from "@/components/rating-badge";
import { StockIdentity } from "@/components/stock-identity";
import { cn } from "@/lib/utils";
import { rankIndices } from "@/lib/indices.mjs";
import { rank } from "@/lib/search.mjs";
import { useMarket } from "@/components/market-provider";
import { loadIndexDirectory, loadSearchIndex } from "@/lib/stock-directory";
import type { IndexInfo, SearchEntry } from "@/lib/types";


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

/*
 * Cmd/Ctrl+K and Escape, shared by every picker on the page.
 *
 * The header's search is mounted on every route and a page can mount its own
 * picker too -- the watchlist's "Add stocks". One window listener serves them
 * all: ⌘K closes whichever is open, and otherwise opens the binding with the
 * highest priority, the latest among equals. The header binds at priority 0
 * and a page's picker at 1, so on the watchlist ⌘K still adds stocks while
 * the header's button still searches. Priority rather than mount order,
 * because React runs a child's effects before its parent's, so on a first
 * load the page's picker would register before the header's.
 */
type Binding = {
  priority: number;
  current: { open: boolean; setOpen: (next: boolean) => void; close: () => void };
};

const bindings: Binding[] = [];

function onShortcut(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    const shown = bindings.filter((binding) => binding.current.open);
    let top: Binding | undefined;
    for (const binding of bindings) {
      if (!top || binding.priority >= top.priority) top = binding;
    }
    if (!top) return;
    event.preventDefault();
    if (shown.length) for (const binding of shown) binding.current.close();
    else top.current.setOpen(true);
  } else if (event.key === "Escape") {
    for (const binding of bindings) if (binding.current.open) binding.current.close();
  }
}

/** Bind Cmd/Ctrl+K and Escape to one picker; see `bindings` above. */
export function useStockPickerShortcut(
  open: boolean,
  setOpen: (next: boolean) => void,
  close: () => void,
  priority = 1,
): void {
  const binding = useRef<Binding | null>(null);

  useEffect(() => {
    const entry: Binding = { priority, current: { open: false, setOpen, close } };
    binding.current = entry;
    bindings.push(entry);
    if (bindings.length === 1) window.addEventListener("keydown", onShortcut);
    return () => {
      bindings.splice(bindings.indexOf(entry), 1);
      binding.current = null;
      if (!bindings.length) window.removeEventListener("keydown", onShortcut);
    };
    // The handlers are refreshed below; re-registering on each change would
    // move this binding to the end of the list and change who wins a tie.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [priority]);

  useEffect(() => {
    if (binding.current) binding.current.current = { open, setOpen, close };
  }, [open, setOpen, close]);
}

type Kind = "all" | "stocks" | "indices";

const KINDS: { value: Kind; label: string }[] = [
  { value: "all", label: "All" },
  { value: "stocks", label: "Stocks" },
  { value: "indices", label: "Indices" },
];

/** Indices shown beside the stocks under "All"; the Indices tab lists every match. */
const INDICES_IN_ALL = 3;

type Result =
  | { kind: "index"; key: string; index: IndexInfo }
  | { kind: "stock"; key: string; entry: SearchEntry };

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
  /** List the market's indices too, under All / Stocks / Indices tabs. */
  onPickIndex,
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
  onPickIndex?: (index: IndexInfo) => void;
}) {
  const market = useMarket();
  const withIndices = onPickIndex !== undefined;
  const [term, setTerm] = useState("");
  const [cursor, setCursor] = useState(0);
  const [kind, setKind] = useState<Kind>("all");
  const [entries, setEntries] = useState<SearchEntry[]>([]);
  const [indices, setIndices] = useState<IndexInfo[]>([]);
  const [status, setStatus] = useState<"idle" | "ready">("idle");
  const inputRef = useRef<HTMLInputElement>(null);

  // One flat list, so the arrow keys walk across both groups. With no term
  // the indices are listed whole: there are a handful, and it is how a reader
  // learns they can be searched at all.
  const results = useMemo<Result[]>(() => {
    const out: Result[] = [];
    if (withIndices && kind !== "stocks") {
      const matched = term.trim() ? rankIndices(indices, term) : indices;
      const shown = kind === "all" && term.trim() ? matched.slice(0, INDICES_IN_ALL) : matched;
      for (const index of shown) out.push({ kind: "index", key: `index:${index.slug}`, index });
    }
    if (!withIndices || kind !== "indices") {
      for (const entry of rank(entries, term)) out.push({ kind: "stock", key: entry.s, entry });
    }
    return out;
  }, [withIndices, kind, term, indices, entries]);

  // Derived rather than its own state: setting a loading flag synchronously in
  // the effect below would cascade an extra render on every open.
  const loading = open && status === "idle";

  // Fetched on first open rather than with the page: the index is ~180 KB and
  // most visits never open the dialog at all. loadSearchIndex() dedupes at module
  // scope, so a double-invoked effect still makes one request.
  useEffect(() => {
    if (!open || status === "ready") return;
    let active = true;
    Promise.all([
      loadSearchIndex(market.slug),
      withIndices ? loadIndexDirectory(market.slug) : Promise.resolve([]),
    ]).then(([loaded, listed]) => {
      if (!active) return;
      setEntries(loaded);
      setIndices(listed);
      setStatus("ready");
    });
    return () => {
      active = false;
    };
  }, [open, status, market.slug, withIndices]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const pick = useCallback(
    (result: Result) => {
      if (result.kind === "index") {
        onPickIndex?.(result.index);
        onClose();
        return;
      }
      onPick(result.entry.s);
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
    [onClose, onPick, onPickIndex, stayOpen],
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
      pick(results[cursor]);
    }
  };

  if (!open) return null;

  const counts = [
    `${entries.length.toLocaleString(market.locale)} stocks`,
    withIndices && indices.length ? `${indices.length} indices` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const firstStock = results.findIndex((result) => result.kind === "stock");
  const hasIndices = results.some((result) => result.kind === "index");
  // Group headings only where both groups are on screen.
  const headed = withIndices && kind === "all" && hasIndices && firstStock >= 0;
  const showHint = !term.trim() && !loading && !hasIndices;

  // Portalled to <body>: the header's search mounts this inside <main>, whose
  // entrance animation makes it a stacking context the sticky header sits
  // above, so the backdrop would dim the page but not the header.
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/20 p-4 pt-[12vh] animate-in fade-in-0 duration-(--duration-spring) ease-(--ease-spring-smooth) dark:bg-black/45"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="glass-thick w-full max-w-lg overflow-hidden rounded-[1.75rem] animate-in fade-in-0 zoom-in-[0.97] slide-in-from-top-2 duration-(--duration-spring) ease-(--ease-spring-smooth)"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="flex items-center gap-2.5 border-b border-(--panel-edge) px-4">
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
            className="h-14 w-full bg-transparent text-base outline-none placeholder:text-muted-foreground"
          />
          <span className="tabular shrink-0 font-mono text-[11px] text-muted-foreground">
            {loading ? "loading…" : counts}
          </span>
        </div>

        {withIndices ? (
          <div role="group" aria-label="Show" className="flex gap-1 border-b border-(--panel-edge) px-3 py-2">
            {KINDS.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={kind === option.value}
                // Keep the caret in the field: a tab is a filter on what is
                // being typed, not a place to move to.
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  setKind(option.value);
                  setCursor(0);
                }}
                className={cn(
                  "h-7 rounded-full px-3 text-xs font-medium",
                  "transition-[background-color,color] duration-(--duration-fast) ease-(--ease-standard)",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  kind === option.value
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-(--control) hover:text-foreground",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        ) : null}

        <ul
          id="stock-picker-results"
          role="listbox"
          aria-label={title}
          className="max-h-[min(24rem,60dvh)] overflow-y-auto overscroll-contain p-1"
        >
          {term.trim() && !results.length && !loading ? (
            <li className="px-3 py-6 text-center text-sm text-muted-foreground">
              No match for &ldquo;{term}&rdquo;.
            </li>
          ) : null}

          {loading ? (
            <li
              aria-live="polite"
              className="px-3 py-6 text-center text-sm text-muted-foreground"
            >
              Loading…
            </li>
          ) : null}

          {results.map((result, index) => {
            const active = index === cursor;
            const heading = headed && (index === 0 || index === firstStock) ? (
              <li role="presentation" className="px-3 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                {result.kind === "index" ? "Indices" : "Stocks"}
              </li>
            ) : null;
            const optionClass = cn(
              "flex w-full items-center gap-3 rounded-[1rem] px-3 py-2 text-left",
              active ? "bg-(--control-hover)" : "hover:bg-(--control)",
            );

            if (result.kind === "index") {
              return (
                <IndexOption
                  key={result.key}
                  heading={heading}
                  index={result.index}
                  active={active}
                  className={optionClass}
                  onHover={() => setCursor(index)}
                  onPick={() => pick(result)}
                />
              );
            }

            const entry = result.entry;
            const isMarked = marked?.has(entry.s) ?? false;
            const isBusy = busySymbol === entry.s;
            return (
              <Fragment key={result.key}>
                {heading}
                <li>
                  <button
                    type="button"
                    role="option"
                    aria-selected={active}
                    onMouseEnter={() => setCursor(index)}
                    onClick={() => pick(result)}
                    className={optionClass}
                  >
                    <span className="tabular w-9 shrink-0 font-mono text-xs text-muted-foreground">
                      {entry.r ?? "—"}
                    </span>
                    <StockIdentity
                      symbol={entry.s}
                      company={entry.c || null}
                      logoDomain={entry.l ?? null}
                      link={false}
                      size="md"
                      className="flex-1"
                    />
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
              </Fragment>
            );
          })}

          {showHint ? (
            <li className="px-3 py-6 text-center text-xs text-muted-foreground">
              {hint ?? "Type a ticker or company name. ↑↓ to move."}
            </li>
          ) : null}
        </ul>
      </div>
    </div>,
    document.body,
  );
}

/**
 * An index in the results: a chart glyph where a stock has its logo, and
 * what its page holds -- the constituents, or only the chart where none are
 * published.
 */
function IndexOption({
  heading,
  index,
  active,
  className,
  onHover,
  onPick,
}: {
  heading: React.ReactNode;
  index: IndexInfo;
  active: boolean;
  className: string;
  onHover: () => void;
  onPick: () => void;
}) {
  return (
    <>
      {heading}
      <li>
        <button
          type="button"
          role="option"
          aria-selected={active}
          onMouseEnter={onHover}
          onClick={onPick}
          className={className}
        >
          <span
            aria-hidden
            className="flex size-8 shrink-0 items-center justify-center rounded-[0.625rem] bg-(--control) text-foreground"
          >
            <ChartLine className="size-4" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold">{index.name}</span>
            <span className="block truncate text-xs text-muted-foreground">
              Index
              {index.members !== null ? ` · ${index.members} stocks` : " · chart"}
            </span>
          </span>
          <ChevronRight
            aria-hidden
            className={cn(
              "size-4 shrink-0 text-muted-foreground transition-[opacity,translate] duration-(--duration-fast) ease-(--ease-standard)",
              active ? "translate-x-0 opacity-100" : "-translate-x-1 opacity-0",
            )}
          />
        </button>
      </li>
    </>
  );
}
