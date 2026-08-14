import Link from "next/link";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Sortable column header.
 *
 * Rendered as a link so sorting is a real navigation: shareable, bookmarkable,
 * and working without client JS. aria-sort is set so assistive technology
 * announces the current order rather than leaving the arrow as a visual-only
 * cue.
 */
export function SortHeader({
  label,
  column,
  currentSort,
  currentDir,
  params,
  numeric = false,
  defaultDir = "desc",
  className,
  title,
}: {
  label: string;
  column: string;
  currentSort: string;
  currentDir: "asc" | "desc";
  params: URLSearchParams;
  numeric?: boolean;
  defaultDir?: "asc" | "desc";
  className?: string;
  title?: string;
}) {
  const active = currentSort === column;
  const nextDir = active
    ? currentDir === "asc"
      ? "desc"
      : "asc"
    : defaultDir;

  const next = new URLSearchParams(params.toString());
  next.set("sort", column);
  next.set("dir", nextDir);
  next.delete("page");

  const Icon = active
    ? currentDir === "asc"
      ? ArrowUp
      : ArrowDown
    : ChevronsUpDown;

  return (
    <th
      scope="col"
      aria-sort={active ? (currentDir === "asc" ? "ascending" : "descending") : "none"}
      className={cn(
        "whitespace-nowrap px-2 py-2 text-[11px] font-semibold uppercase tracking-wide",
        numeric ? "text-right" : "text-left",
        className,
      )}
      title={title}
    >
      <Link
        href={`?${next.toString()}`}
        scroll={false}
        className={cn(
          "group/sort inline-flex items-center gap-1 rounded hover:text-foreground",
          "transition-colors duration-(--duration-fast) ease-(--ease-standard)",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          numeric && "flex-row-reverse",
          active ? "text-foreground" : "text-muted-foreground",
        )}
      >
        {label}
        {/*
          The icon swaps element between states, so the direction change itself
          cannot be tweened. What is animated is the affordance: an unsorted
          column's chevron lifts from 40% to full opacity on hover, which tells
          the reader the header is sortable before they click it.
        */}
        <Icon
          className={cn(
            "size-3 transition-opacity duration-(--duration-fast)",
            active ? "opacity-100" : "opacity-40 group-hover/sort:opacity-100",
          )}
          aria-hidden
        />
      </Link>
    </th>
  );
}

/** Non-sortable header, kept visually identical to SortHeader. */
export function PlainHeader({
  label,
  numeric = false,
  className,
  title,
}: {
  label: string;
  numeric?: boolean;
  className?: string;
  title?: string;
}) {
  return (
    <th
      scope="col"
      className={cn(
        "whitespace-nowrap px-2 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground",
        numeric ? "text-right" : "text-left",
        className,
      )}
      title={title}
    >
      {label}
    </th>
  );
}
