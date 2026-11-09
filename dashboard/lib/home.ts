import "server-only";

import type { ReactNode } from "react";

import { localDay } from "@/lib/market-calendar.mjs";
import type { Market } from "@/lib/markets";

/** Today on the market's own clock, "YYYY-MM-DD": what "this week" is measured from. */
export function marketToday(market: Market): string {
  return localDay(Date.now(), market.timezone);
}

/** `day` plus `days`, as "YYYY-MM-DD" (dates are calendar days, so UTC arithmetic is exact). */
export function addDays(day: string, days: number): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/**
 * Wraps a card's async server component so its data time is logged once per
 * render ("home card <name> 123ms"), which names the slow card in the Vercel
 * logs. The card itself is unchanged.
 */
export function withTiming<P>(name: string, card: (props: P) => Promise<ReactNode>) {
  return async function Timed(props: P) {
    const started = Date.now();
    try {
      return await card(props);
    } finally {
      console.info(`home card ${name} ${Date.now() - started}ms`);
    }
  };
}
