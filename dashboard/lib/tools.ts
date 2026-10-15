import { FileSpreadsheet, MessagesSquare, TrendingUp, type LucideIcon } from "lucide-react";

/**
 * The tools, in one place: views beside the ranking -- the season's calls and
 * results, and how past rankings would have done. This list is what the Tools tab in the header stays lit for
 * (app-shell) and what the row beneath it offers (ToolsNav). A new tool is one
 * entry here and one folder under `app/(app)/[market]/(tools)`.
 *
 * A plain module, not part of ToolsNav: the header is a server component, and
 * a value imported from a client module arrives there as a reference, not as
 * the array.
 */
export const TOOLS: readonly { path: string; label: string; icon: LucideIcon }[] = [
  { path: "/concalls", label: "Concalls", icon: MessagesSquare },
  { path: "/results", label: "Results", icon: FileSpreadsheet },
  { path: "/returns", label: "Returns", icon: TrendingUp },
];
