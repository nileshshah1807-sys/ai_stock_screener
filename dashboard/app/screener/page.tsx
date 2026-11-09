import { redirect } from "next/navigation";

import { DEFAULT_MARKET_SLUG, marketPath } from "@/lib/markets";

/**
 * The app's front door. proxy.ts sends a visitor who is not signed in to
 * /login and back here afterwards; a signed-in one lands on Home.
 * No market preference is stored per person, so this is the default market,
 * as the bare root was before the landing page took it over.
 */
export default function ScreenerEntry() {
  redirect(marketPath(DEFAULT_MARKET_SLUG));
}
