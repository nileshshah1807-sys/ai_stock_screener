"use client";

import { TableSkeleton } from "@/components/skeletons";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";

/**
 * The stocks behind one breadth chart, in the screener's own table.
 *
 * A sheet that rises over the page rather than a navigation away from it: the
 * reader came from a chart and goes back to it, so the charts stay where they
 * were -- same range, same scroll -- underneath. It opens on the press, before
 * the rows have arrived, with a skeleton of the table in place; the rows then
 * fill the same box, so nothing jumps.
 *
 * The table itself is rendered on the server and passed in, so every column,
 * sort key and link is the screener's. Sorting and paging are links that keep
 * `?list=` in the URL, which is why the sheet survives them, and why Back
 * closes it.
 */
export function BreadthListSheet({
  open,
  onClose,
  title,
  detail,
  loading,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  detail: string;
  loading: boolean;
  children: React.ReactNode;
}) {
  return (
    <Sheet open={open} onOpenChange={(next) => (next ? null : onClose())}>
      <SheetContent
        side="bottom"
        className="gap-0 p-0 data-[side=bottom]:h-[min(88dvh,64rem)] sm:data-[side=bottom]:inset-x-6 sm:data-[side=bottom]:bottom-6 lg:data-[side=bottom]:inset-x-10"
      >
        {/* A grabber, as on an iOS sheet: it says the surface is a layer
            that will go back down, not a page that replaced the last one. */}
        <span aria-hidden className="mx-auto mt-2.5 h-1 w-9 shrink-0 rounded-full bg-foreground/15" />
        <div className="shrink-0 px-5 pt-3 pb-4 pr-14 sm:px-6">
          <SheetTitle className="text-lead font-semibold tracking-[-0.011em]">{title}</SheetTitle>
          <SheetDescription className="tabular mt-0.5 text-sm">{detail}</SheetDescription>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-4 sm:px-5 sm:pb-5">
          <div aria-busy={loading} className="space-y-4">
            {loading ? <TableSkeleton rows={10} /> : children}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
