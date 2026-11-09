import "server-only";

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
