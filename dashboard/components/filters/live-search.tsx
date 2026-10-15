"use client";

import { useEffect, useState, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Loader2, Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/**
 * The search field every list in the dashboard filters by: a magnifier, the
 * input, and a spinner while the server's answer is on its way.
 *
 * Presentational; LiveSearch below connects it to the URL. The screener's
 * filter bar uses this directly because it also hides on-screen rows on
 * every keystroke before the server answers.
 */
export function SearchInput({
  value,
  onChange,
  label,
  placeholder,
  pending = false,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  /** What is searched, for a screen reader. */
  label: string;
  placeholder: string;
  pending?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("relative", className)}>
      <Search
        className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
      <Input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={label}
        autoComplete="off"
        className="h-9 pl-8"
      />
      {pending ? (
        <Loader2
          className="absolute right-2.5 top-1/2 size-3.5 -translate-y-1/2 animate-spin text-muted-foreground"
          aria-hidden
        />
      ) : null}
    </div>
  );
}

/** One request per pause in typing, not one per keystroke. */
const DEBOUNCE_MS = 200;
// A constant, so a caller that names no resets does not re-arm the timer on
// every render with a fresh empty array.
const NO_RESETS: readonly string[] = [];

/**
 * A search that filters as it is typed: the text goes into the URL's `q`
 * after a short pause, and the server component re-renders with it. Every
 * other search param rides along, so the filters already chosen stay; the
 * ones named in `resets` (a page number, a "show more" count) are dropped,
 * since they describe the list before this search.
 *
 * It replaces the URL rather than pushing a history entry, so Back leaves
 * the page instead of stepping through every prefix that was typed.
 */
export function LiveSearch({
  label,
  placeholder,
  param = "q",
  resets = NO_RESETS,
  className,
}: {
  label: string;
  placeholder: string;
  param?: string;
  resets?: readonly string[];
  className?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();
  const current = searchParams.get(param) ?? "";
  const [query, setQuery] = useState(current);
  const [synced, setSynced] = useState(current);

  // The URL changed from elsewhere -- "Clear search and filters", Back. Take
  // its text, unless it is only what this field already holds, trimmed: the
  // reader may be mid-word after a space.
  if (current !== synced) {
    setSynced(current);
    if (current !== query.trim()) setQuery(current);
  }

  useEffect(() => {
    const text = query.trim();
    if (text === current) return;
    const timer = setTimeout(() => {
      const params = new URLSearchParams(searchParams.toString());
      if (text) params.set(param, text);
      else params.delete(param);
      for (const key of resets) params.delete(key);
      const search = params.toString();
      startTransition(() => {
        router.replace(search ? `${pathname}?${search}` : pathname, { scroll: false });
      });
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query, current, param, resets, pathname, router, searchParams]);

  return (
    <SearchInput
      value={query}
      onChange={setQuery}
      label={label}
      placeholder={placeholder}
      pending={pending}
      className={className}
    />
  );
}
