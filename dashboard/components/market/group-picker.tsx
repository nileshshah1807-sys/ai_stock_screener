"use client";

import { useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { BreadthGroup } from "@/lib/queries";
import { cn } from "@/lib/utils";

export type GroupKey = { scope: "market" | "sector" | "industry"; name: string };

/**
 * Chooses which stocks the breadth charts count: all of them, one sector, or
 * one industry.
 *
 * A searchable popover rather than a native select. With ~90 industries a
 * select is a long scroll with nothing to type into; here typing narrows both
 * lists at once, and each industry shows the sector it belongs to so two
 * similarly named ones can be told apart. Member counts are shown because a
 * percentage of eight stocks and a percentage of four hundred read very
 * differently.
 */
export function GroupPicker({
  groups,
  selected,
  total,
  onSelect,
}: {
  groups: BreadthGroup[];
  selected: GroupKey;
  total: number | null;
  onSelect: (group: GroupKey) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const input = useRef<HTMLInputElement>(null);

  const { sectors, industries } = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const match = (group: BreadthGroup) =>
      !needle ||
      group.name.toLowerCase().includes(needle) ||
      (group.parent ?? "").toLowerCase().includes(needle);
    return {
      sectors: groups.filter((group) => group.scope === "sector" && match(group)),
      industries: groups.filter((group) => group.scope === "industry" && match(group)),
    };
  }, [groups, query]);

  const choose = (group: GroupKey) => {
    setOpen(false);
    setQuery("");
    onSelect(group);
  };

  const label = selected.scope === "market" ? "All stocks" : selected.name;
  const showAll = !query.trim() || "all stocks".includes(query.trim().toLowerCase());

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery("");
      }}
    >
      <PopoverTrigger
        className={cn(
          "inline-flex h-9 max-w-full min-w-0 items-center gap-2 rounded-full bg-(--control) py-2 pr-3 pl-4 text-sm font-medium",
          "transition-[background-color,transform] duration-(--duration-fast) ease-(--ease-standard) hover:bg-(--control-hover)",
          "active:scale-[0.97] active:duration-(--duration-press)",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        )}
      >
        <span className="truncate">{label}</span>
        <ChevronDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      </PopoverTrigger>

      <PopoverContent
        align="start"
        className="w-[min(22rem,calc(100vw-2rem))] gap-2 p-2"
        initialFocus={input}
      >
        <label className="flex items-center gap-2 rounded-[0.75rem] bg-(--control) px-3 py-2">
          <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <input
            ref={input}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search sectors and industries"
            aria-label="Search sectors and industries"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
        </label>

        <div className="max-h-[min(24rem,60vh)] overflow-y-auto overscroll-contain" role="listbox" aria-label="Stock group">
          {showAll ? (
            <Option
              active={selected.scope === "market"}
              onClick={() => choose({ scope: "market", name: "" })}
              label="All stocks"
              count={total}
            />
          ) : null}

          {sectors.length ? <Heading>Sectors</Heading> : null}
          {sectors.map((group) => (
            <Option
              key={`s-${group.name}`}
              active={selected.scope === "sector" && selected.name === group.name}
              onClick={() => choose({ scope: "sector", name: group.name })}
              label={group.name}
              count={group.members}
            />
          ))}

          {industries.length ? <Heading>Industries</Heading> : null}
          {industries.map((group) => (
            <Option
              key={`i-${group.name}`}
              active={selected.scope === "industry" && selected.name === group.name}
              onClick={() => choose({ scope: "industry", name: group.name })}
              label={group.name}
              detail={group.parent}
              count={group.members}
            />
          ))}

          {!showAll && !sectors.length && !industries.length ? (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">
              No sector or industry matches &ldquo;{query.trim()}&rdquo;.
            </p>
          ) : null}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function Heading({ children }: { children: React.ReactNode }) {
  return (
    <p className="sticky top-0 z-10 bg-(--glass-thick) px-3 pt-3 pb-1 text-[0.6875rem] font-semibold tracking-[0.04em] text-muted-foreground uppercase backdrop-blur">
      {children}
    </p>
  );
}

function Option({
  active,
  onClick,
  label,
  detail,
  count,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  detail?: string | null;
  count: number | null;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 rounded-[0.75rem] px-3 py-2 text-left text-sm",
        "transition-colors duration-(--duration-fast) hover:bg-(--control-hover)",
        "focus-visible:bg-(--control-hover) focus-visible:outline-none",
      )}
    >
      <Check className={cn("size-4 shrink-0", active ? "opacity-100" : "opacity-0")} aria-hidden />
      <span className="min-w-0 flex-1">
        <span className={cn("block truncate", active && "font-semibold")}>{label}</span>
        {detail ? <span className="block truncate text-xs text-muted-foreground">{detail}</span> : null}
      </span>
      {count !== null ? (
        <span className="tabular shrink-0 font-mono text-xs text-muted-foreground">{count}</span>
      ) : null}
    </button>
  );
}
