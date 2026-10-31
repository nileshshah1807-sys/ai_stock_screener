import { CalendarClock } from "lucide-react";

import { formatDate } from "@/lib/format";

/** The date the company told the exchange its board will approve results. A date, never a time. */
export function UpcomingResultChip({ date }: { date: string }) {
  return (
    <p className="mb-3 inline-flex items-center gap-1.5 rounded-md bg-caution/10 px-2.5 py-1 text-xs font-medium text-caution">
      <CalendarClock className="size-3.5" aria-hidden />
      Upcoming result · {formatDate(date)}
    </p>
  );
}
