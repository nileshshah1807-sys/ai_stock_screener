import Link from "next/link";
import { FileText, MessageSquareText, type LucideIcon } from "lucide-react";

import { MISSING } from "@/lib/format";
import { marketPath, type Market } from "@/lib/markets";
import { describeEvent } from "@/lib/notifications.mjs";
import type { MarketEvent } from "@/lib/notifications";
import { cn } from "@/lib/utils";

const ICONS: Record<string, LucideIcon> = {
  results: FileText,
  transcript: MessageSquareText,
};

/**
 * One event, as a link to the stock it is about.
 *
 * The same row in the bell's popover and on the full page, so an event reads
 * identically in both. No hooks and no clock: `time` is passed in already
 * formatted, because the popover wants a relative age computed in the browser
 * and the page wants the exchange's wall clock rendered on the server, and a
 * row that called Date.now() itself would hydrate to a different string than
 * the server sent.
 *
 * Unread is carried twice, as the dot and as weight on the symbol, so it does
 * not depend on colour alone.
 */
export function EventRow({
  event,
  market,
  unread,
  time,
  onNavigate,
}: {
  event: MarketEvent;
  market: Market;
  unread: boolean;
  time: string | null;
  onNavigate?: () => void;
}) {
  const { title, summary, tab } = describeEvent(event);
  const Icon = ICONS[event.kind] ?? FileText;
  const href =
    marketPath(market.slug, `/stocks/${encodeURIComponent(event.symbol)}`) +
    (tab ? `?tab=${tab}` : "");

  return (
    <Link
      href={href}
      // A feed of sixty rows would otherwise prefetch sixty stock pages to
      // serve the one that is clicked; the route has its own loading state.
      prefetch={false}
      onClick={onNavigate}
      className={cn(
        "group flex items-center gap-3 px-4 py-2.5",
        "transition-colors duration-(--duration-fast) ease-(--ease-standard) hover:bg-muted/50",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "size-1.5 shrink-0 rounded-full",
          unread ? "bg-primary" : "bg-transparent",
        )}
      />
      <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-(--control) text-muted-foreground">
        <Icon className="size-4" aria-hidden />
      </span>

      {/*
        The time shares the first line with the names rather than standing in
        its own column: beside both lines it took the width the second line
        needs, and "Quarter ended Sep 2026" -- the point of the row -- was the
        text that got truncated.
      */}
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span
            className={cn(
              "shrink-0 font-mono text-xs underline-offset-2 group-hover:underline",
              unread ? "font-semibold text-foreground" : "font-medium text-foreground/80",
            )}
          >
            {event.symbol}
          </span>
          <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
            {event.company ?? MISSING}
          </span>
          {time ? (
            <span className="tabular shrink-0 font-mono text-[11px] text-muted-foreground">
              {time}
            </span>
          ) : null}
        </span>
        <span className="block truncate text-xs text-muted-foreground">
          <span className="text-foreground/90">{title}</span>
          {summary ? ` · ${summary}` : ""}
        </span>
      </span>

      {unread ? <span className="sr-only">Unread</span> : null}
    </Link>
  );
}
