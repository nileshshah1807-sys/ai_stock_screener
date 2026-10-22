"use client";

import { useId, useMemo, useState } from "react";
import { ChevronDown, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export type FilterOption = { value: string; label: string; count?: number };

/**
 * One dropdown of a filter bar: a button that names what it filters and how
 * many values are chosen, opening a checklist.
 *
 * Holds no selection of its own. The bar owns it and the URL records it, so
 * the same dropdown reads correctly after a reload or from a shared link.
 */
export function FilterMultiSelect({
  label,
  options,
  selected,
  onChange,
  searchable = false,
  emptyText = "Nothing to choose from.",
  align = "start",
  disabled = false,
  title,
}: {
  label: string;
  options: FilterOption[];
  selected: string[];
  onChange: (next: string[]) => void;
  /** A search box above the list, for a list too long to scan. */
  searchable?: boolean;
  emptyText?: string;
  align?: "start" | "end";
  disabled?: boolean;
  title?: string;
}) {
  const id = useId();
  const [term, setTerm] = useState("");

  const shown = useMemo(() => {
    const needle = term.trim().toLowerCase();
    return needle ? options.filter((option) => option.label.toLowerCase().includes(needle)) : options;
  }, [options, term]);

  const toggle = (value: string) =>
    onChange(selected.includes(value) ? selected.filter((item) => item !== value) : [...selected, value]);

  return (
    <Popover onOpenChange={(open) => (open ? undefined : setTerm(""))}>
      <PopoverTrigger
        disabled={disabled}
        render={
          <Button
            variant="outline"
            title={title}
            aria-label={selected.length ? `${label}, ${selected.length} selected` : label}
            className={cn("gap-1.5", selected.length ? "pr-2.5" : "pr-3")}
          />
        }
      >
        {label}
        {selected.length ? (
          <span className="tabular rounded-md bg-primary px-1.5 text-[10px] font-semibold leading-4 text-primary-foreground">
            {selected.length}
          </span>
        ) : null}
        <ChevronDown className="size-3.5 text-muted-foreground" aria-hidden />
      </PopoverTrigger>

      <PopoverContent align={align} className="w-[min(18rem,calc(100vw-2rem))] gap-2">
        {searchable ? (
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              type="search"
              value={term}
              onChange={(event) => setTerm(event.target.value)}
              placeholder={`Search ${label.toLowerCase()}…`}
              aria-label={`Search ${label.toLowerCase()}`}
              autoComplete="off"
              className="h-8 pl-8"
            />
          </div>
        ) : null}

        {shown.length ? (
          <ul className="-mx-1 max-h-72 overflow-y-auto" aria-label={label}>
            {shown.map((option, index) => {
              const optionId = `${id}-${index}`;
              return (
                <li key={option.value}>
                  <label
                    htmlFor={optionId}
                    className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 text-sm hover:bg-(--control-hover)"
                  >
                    <Checkbox
                      id={optionId}
                      checked={selected.includes(option.value)}
                      onCheckedChange={() => toggle(option.value)}
                    />
                    <span className="min-w-0 flex-1 truncate">{option.label}</span>
                    {option.count === undefined ? null : (
                      <span className="tabular font-mono text-[11px] text-muted-foreground">
                        {option.count}
                      </span>
                    )}
                  </label>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="px-1 py-2 text-xs text-muted-foreground">
            {options.length ? `No ${label.toLowerCase()} matches “${term.trim()}”.` : emptyText}
          </p>
        )}

        {selected.length ? (
          <Button variant="ghost" size="sm" className="self-start" onClick={() => onChange([])}>
            Clear
          </Button>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
