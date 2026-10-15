"use client";

import Link from "next/link";
import { use, useEffect, useState, useTransition } from "react";
import { Bell } from "lucide-react";

import { markNotificationsSeen } from "@/app/(app)/[market]/notifications/actions";
import { EventRow } from "@/components/notifications/event-row";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { formatRelativeAge } from "@/lib/format";
import { marketPath, type Market } from "@/lib/markets";
import { badgeText, isUnread } from "@/lib/notifications.mjs";
import type { BellState } from "@/lib/notifications";
import { cn } from "@/lib/utils";

/** Fired by the notifications page, which marks the feed seen on arrival. */
export const NOTIFICATIONS_SEEN_EVENT = "winnow:notifications-seen";

/**
 * The bell in the header's account capsule.
 *
 * Opening it is reading it: the badge clears as the panel opens and the server
 * is told in the background. The rows keep their unread marks for as long as
 * the panel stays open -- they are measured against the `seenAt` the layout
 * rendered with -- so the reader can still see which ones were new.
 *
 * The count lives in client state because the market layout that supplies it
 * does not re-render on navigation. That is deliberate there (the chrome must
 * not reload when the grid is sorted); here it means the bell has to clear
 * itself rather than wait for the server to say so.
 *
 * The state arrives as a promise and the shell renders it inside Suspense:
 * its reads take two rounds (what the viewer watches and when they last
 * looked, then the events and the count), and awaiting them in the layout held
 * the whole page back behind the one control that is not the page.
 */
export function NotificationBell({
  market,
  state: stateRead,
}: {
  market: Market;
  state: Promise<BellState>;
}) {
  const state = use(stateRead);
  const [unread, setUnread] = useState(state.unread);
  const [open, setOpen] = useState(false);
  const [, startTransition] = useTransition();
  const badge = badgeText(unread);

  useEffect(() => {
    const clear = () => setUnread(0);
    window.addEventListener(NOTIFICATIONS_SEEN_EVENT, clear);
    return () => window.removeEventListener(NOTIFICATIONS_SEEN_EVENT, clear);
  }, []);

  const onOpenChange = (next: boolean) => {
    setOpen(next);
    if (next && unread > 0) {
      setUnread(0);
      startTransition(() => markNotificationsSeen(market.slug));
    }
  };

  const label = badge
    ? `Notifications, ${unread} unread`
    : "Notifications";

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            className="relative rounded-full hover:bg-(--control-hover)"
            aria-label={label}
            title="Notifications"
          />
        }
      >
        <Bell className="size-4" aria-hidden />
        {badge ? (
          <span
            aria-hidden
            className={cn(
              "tabular absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center",
              "rounded-full bg-primary px-1 font-mono text-[10px] leading-none font-semibold text-primary-foreground",
              // A ring in the page ground, so the badge reads as sitting on
              // the capsule rather than cut into the bell's outline.
              "ring-2 ring-background",
            )}
          >
            {badge}
          </span>
        ) : null}
      </PopoverTrigger>

      <PopoverContent align="end" sideOffset={10} className="w-[min(22rem,calc(100vw-1.5rem))] gap-0 p-0">
        <div className="flex items-baseline justify-between gap-3 px-4 pt-3.5 pb-2.5">
          <PopoverTitle className="text-sm font-semibold tracking-[-0.011em]">
            Notifications
          </PopoverTitle>
          <span className="text-[11px] text-muted-foreground">
            {state.watching ? "Your watchlists" : `All of ${market.label}`}
          </span>
        </div>

        {state.events.length ? (
          <ul className="max-h-[min(24rem,60dvh)] divide-y overflow-y-auto border-y">
            {state.events.map((event) => (
              <li key={event.id}>
                <EventRow
                  event={event}
                  market={market}
                  unread={isUnread(event, state.seenAt)}
                  time={formatRelativeAge(event.occurred_at)}
                  onNavigate={() => setOpen(false)}
                />
              </li>
            ))}
          </ul>
        ) : (
          <p className="border-y px-4 py-8 text-center text-xs text-muted-foreground">
            {state.watching
              ? "Nothing new for the companies on your watchlists."
              : "No results or transcripts recorded yet."}
          </p>
        )}

        <Link
          href={marketPath(market.slug, "/notifications")}
          onClick={() => setOpen(false)}
          className="block rounded-b-(--radius-glass) px-4 py-2.5 text-center text-xs font-medium text-foreground transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        >
          See all notifications
        </Link>
      </PopoverContent>
    </Popover>
  );
}

/**
 * The bell while its state is on the way: the same button at the same size,
 * so nothing in the capsule moves when the count arrives.
 */
export function NotificationBellFallback() {
  return (
    <Button
      variant="ghost"
      size="icon"
      className="relative rounded-full"
      aria-label="Notifications"
      title="Notifications"
      disabled
    >
      <Bell className="size-4" aria-hidden />
    </Button>
  );
}
