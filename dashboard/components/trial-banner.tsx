import Link from "next/link";
import { Hourglass } from "lucide-react";

import { daysLeftLabel } from "@/lib/billing.mjs";
import { cn } from "@/lib/utils";

/**
 * Shown to someone on the free trial, under the header, in the same inset form
 * as the freshness notice. Quiet until the last two days, then caution-toned.
 * Nobody else sees it: paid, invited and admin accounts have nothing to count.
 */
export function TrialBanner({ days }: { days: number }) {
  const soon = days <= 2;
  return (
    <div
      role="status"
      className={cn(
        "mx-4 mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-4 py-2.5 text-sm sm:mx-6",
        soon ? "border-caution/30 bg-caution/8 text-caution" : "bg-(--control)",
      )}
    >
      <Hourglass className="size-4 shrink-0" aria-hidden />
      <span className="font-medium">Free trial: {daysLeftLabel(days)}</span>
      <Link
        href="/pricing"
        className="rounded underline underline-offset-2 hover:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        See the plan
      </Link>
    </div>
  );
}
