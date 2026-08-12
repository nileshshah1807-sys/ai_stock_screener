import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { formatInteger } from "@/lib/format";

export function Pagination({
  page,
  pageSize,
  total,
  params,
}: {
  page: number;
  pageSize: number;
  total: number;
  params: URLSearchParams;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  const href = (target: number) => {
    const next = new URLSearchParams(params.toString());
    if (target <= 1) next.delete("page");
    else next.set("page", String(target));
    return `?${next.toString()}`;
  };

  return (
    <nav
      aria-label="Pagination"
      className="flex items-center justify-between gap-4 text-sm"
    >
      <p className="tabular text-muted-foreground">
        {total === 0 ? (
          "No results"
        ) : (
          <>
            <span className="font-medium text-foreground">
              {formatInteger(from)}–{formatInteger(to)}
            </span>{" "}
            of {formatInteger(total)}
          </>
        )}
      </p>

      <div className="flex items-center gap-1">
        {/* Disabled controls are rendered as spans, not links: a disabled
            anchor is still focusable and still navigable by keyboard. */}
        {page > 1 ? (
          <Link
            href={href(page - 1)}
            scroll={false}
            rel="prev"
            className={cn(
              "inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5",
              "hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            )}
          >
            <ChevronLeft className="size-3.5" aria-hidden />
            Previous
          </Link>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-muted-foreground/50">
            <ChevronLeft className="size-3.5" aria-hidden />
            Previous
          </span>
        )}

        <span className="tabular px-2 text-xs text-muted-foreground">
          Page {page} of {pages}
        </span>

        {page < pages ? (
          <Link
            href={href(page + 1)}
            scroll={false}
            rel="next"
            className={cn(
              "inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5",
              "hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            )}
          >
            Next
            <ChevronRight className="size-3.5" aria-hidden />
          </Link>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-muted-foreground/50">
            Next
            <ChevronRight className="size-3.5" aria-hidden />
          </span>
        )}
      </div>
    </nav>
  );
}
