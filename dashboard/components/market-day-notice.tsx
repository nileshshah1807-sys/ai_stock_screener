"use client";

import { useSyncExternalStore } from "react";
import { CalendarDays, X } from "lucide-react";

import { useMarket, useMarketDay } from "@/components/market-provider";
import { noticeDismissKey, noticeText } from "@/lib/market-calendar.mjs";
import { cn } from "@/lib/utils";

const listeners = new Set<() => void>();
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => void listeners.delete(listener);
};

function dismissedToday(key: string) {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

/**
 * Says why the exchange is shut today, or that a special session (Muhurat
 * trading) is on. A dismissible notice, not a modal: closing it hides it for
 * the rest of that day in this browser. It renders nothing on an ordinary
 * day, and nothing when the calendar table has no row or is not applied.
 * The server picked the row for today, so a tab left open past midnight keeps
 * showing yesterday's until it navigates; the live-price label checks the day.
 */
export function MarketDayNotice() {
  const market = useMarket();
  const today = useMarketDay();
  const key = today ? noticeDismissKey(market.code, today.day) : "";
  // Hidden on the server and until the stored choice is read, so a dismissed
  // notice never flashes.
  const dismissed = useSyncExternalStore(
    subscribe,
    () => dismissedToday(key),
    () => true,
  );

  const text = noticeText(today, market.timezoneLabel);
  if (!text || dismissed) return null;

  const holiday = today?.kind === "holiday";
  const dismiss = () => {
    try {
      window.localStorage.setItem(key, "1");
    } catch {
      // Private mode: it comes back on the next page, which is acceptable.
    }
    for (const listener of listeners) listener();
  };

  return (
    <div
      role="status"
      className={cn(
        "flex items-start gap-2.5 rounded-lg border px-4 py-3 text-sm",
        holiday ? "border-caution/30 bg-caution/8 text-caution" : "bg-(--control)",
      )}
    >
      <CalendarDays className="mt-0.5 size-4 shrink-0" aria-hidden />
      <p className="flex-1 font-medium">{text}</p>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss"
        className="-m-1 rounded p-1 opacity-70 hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <X className="size-4" aria-hidden />
      </button>
    </div>
  );
}
