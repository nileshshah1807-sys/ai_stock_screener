import Link from "next/link";
import { FileText, MessageSquareText, type LucideIcon } from "lucide-react";

import { HomeCard } from "@/components/home/home-card";
import { StockIdentity } from "@/components/stock-identity";
import { getBellState, type MarketEvent } from "@/lib/notifications";
import { describeEvent, groupBySymbol, quarterLabel } from "@/lib/notifications.mjs";
import { marketPath, type Market } from "@/lib/markets";
import { cn } from "@/lib/utils";

const CHIPS: Record<string, { label: string; Icon: LucideIcon }> = {
  results: { label: "Results", Icon: FileText },
  transcript: { label: "Transcript", Icon: MessageSquareText },
};

function Chip({ event, market, unread }: { event: MarketEvent; market: Market; unread: boolean }) {
  const { label, Icon } = CHIPS[event.kind] ?? { label: describeEvent(event).title, Icon: FileText };
  const { tab } = describeEvent(event);
  const quarter = quarterLabel(event.detail?.period ?? event.detail?.quarter ?? event.event_key);
  const href = marketPath(market.slug, `/stocks/${encodeURIComponent(event.symbol)}`) + (tab ? `?tab=${tab}` : "");
  return (
    <Link
      href={href}
      prefetch={false}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        "transition-colors duration-(--duration-fast) hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        unread ? "border-primary/40 text-foreground" : "border-border text-muted-foreground",
      )}
    >
      <Icon className="size-3" aria-hidden />
      {label}
      {quarter ? <span className="font-normal text-muted-foreground"> · {quarter}</span> : null}
    </Link>
  );
}

/**
 * What changed on the viewer's lists since they last opened the feed: one row
 * per stock, with a chip for each thing it published. It is the bell's own
 * state (`getBellState`, cached per request), so the count here is the number
 * on the bell and costs no extra read.
 */
export async function SinceCard({ market }: { market: Market }) {
  const { events, unread, seenAt } = await getBellState(market.code);
  if (!events.length) return null;
  const seen = seenAt ? Date.parse(seenAt) : 0;
  const groups = groupBySymbol(events);

  return (
    <HomeCard title="Since you last visited" note={unread ? `${unread} new` : "All caught up"}>
      <ul className="divide-y divide-border">
        {groups.map((group) => {
          const isNew = group.events.some((event) => Date.parse(event.detected_at) > seen);
          return (
            <li key={group.symbol} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5">
              <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", isNew ? "bg-primary" : "bg-transparent")} />
              <StockIdentity symbol={group.symbol} company={group.company} className="min-w-0 flex-1 basis-40" />
              <span className="flex flex-wrap gap-1.5">
                {group.events.map((event) => (
                  <Chip key={event.id} event={event} market={market} unread={Date.parse(event.detected_at) > seen} />
                ))}
              </span>
            </li>
          );
        })}
      </ul>
    </HomeCard>
  );
}
