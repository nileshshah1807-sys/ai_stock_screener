import { redirect } from "next/navigation";

import { DEFAULT_MARKET_SLUG, marketPath } from "@/lib/markets";

/**
 * The bare root has no market, so it cannot show a grid.
 *
 * Redirecting rather than rendering NSE at `/` keeps one URL per view: every
 * bookmark, share and export link carries the market it was taken from, and
 * there is no second address for the same page. Links saved before markets
 * existed were NSE links, which is exactly where this sends them.
 */
export default function RootPage() {
  redirect(marketPath(DEFAULT_MARKET_SLUG));
}
