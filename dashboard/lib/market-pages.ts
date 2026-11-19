import { Activity, ArrowUpDown, Grid3x3, type LucideIcon } from "lucide-react";

/**
 * The Market tab's pages: what is moving now, how each sector is doing, and
 * how broad the move is. This list is what the Market tab in the header stays
 * lit for (app-shell) and what the row beneath it offers (SubNav). A new page
 * is one entry here and one folder under `app/(app)/[market]/(market)`.
 *
 * A plain module for the same reason as lib/tools.ts: the header is a server
 * component and needs the array, not a client reference.
 */
export const MARKET_PAGES: readonly { path: string; label: string; icon: LucideIcon; adminOnly?: boolean }[] = [
  { path: "/market", label: "Today’s movers", icon: ArrowUpDown },
  { path: "/sectors", label: "Sectors", icon: Grid3x3 },
  { path: "/breadth", label: "Breadth", icon: Activity },
];
