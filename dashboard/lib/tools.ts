import { ChartArea, FileSpreadsheet, MessagesSquare, type LucideIcon } from "lucide-react";

/**
 * The tools, in one place: views that look across the market rather than rank
 * its stocks. This list is what the Tools tab in the header stays lit for
 * (app-shell) and what the row beneath it offers (ToolsNav). A new tool is one
 * entry here and one folder under `app/(app)/[market]/(tools)`.
 *
 * A plain module, not part of ToolsNav: the header is a server component, and
 * a value imported from a client module arrives there as a reference, not as
 * the array.
 */
export const TOOLS: readonly { path: string; label: string; icon: LucideIcon }[] = [
  { path: "/market", label: "Market", icon: ChartArea },
  { path: "/concalls", label: "Concalls", icon: MessagesSquare },
  { path: "/results", label: "Results", icon: FileSpreadsheet },
];
