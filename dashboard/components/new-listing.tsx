import { Clock } from "lucide-react";

import { cn } from "@/lib/utils";
import { formatMoneyCompact } from "@/lib/format";
import { historyProgress, statusDetail } from "@/lib/new-listings.mjs";
import type { NewListingRow } from "@/lib/queries";
import type { Market } from "@/lib/markets";

/**
 * "Not rated" rather than a rating-coloured chip. A new listing has no
 * position on the STRONG BUY -> SELL scale, and borrowing any of its colours
 * would imply one; the neutral chip with a clock says "waiting", which is the
 * whole state.
 */
export function NotRatedBadge({
  className,
  size = "sm",
}: {
  className?: string;
  size?: "sm" | "md";
}) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border border-dashed border-border bg-(--control) font-semibold tracking-[0.02em] text-muted-foreground uppercase",
        size === "md" ? "px-2.5 py-1 text-[11px]" : "px-2 py-0.5 text-[10px]",
        className,
      )}
    >
      <Clock className={size === "md" ? "size-3.5" : "size-3"} aria-hidden />
      Not rated
    </span>
  );
}

/** Sessions of price history against the model's minimum. */
export function HistoryBar({ row, className }: { row: NewListingRow; className?: string }) {
  const progress = historyProgress(row);
  const complete = progress >= 1;
  return (
    <div className={cn("space-y-1", className)}>
      <div
        role="meter"
        aria-label="Price history toward the rating minimum"
        aria-valuemin={0}
        aria-valuemax={row.sessions_required}
        aria-valuenow={Math.min(row.sessions ?? 0, row.sessions_required)}
        className="h-1.5 overflow-hidden rounded-full bg-(--control)"
      >
        <div
          className={cn(
            "bar-grow h-full rounded-full",
            complete ? "bg-positive" : "bg-foreground/70",
          )}
          style={{ width: `${Math.max(progress * 100, 2)}%` }}
        />
      </div>
      <p className="tabular text-[11px] text-muted-foreground">
        {row.sessions ?? 0} / {row.sessions_required} sessions
      </p>
    </div>
  );
}

export function listingDetail(row: NewListingRow, market: Market) {
  return statusDetail(row, (value: number | null) => formatMoneyCompact(value, market));
}
