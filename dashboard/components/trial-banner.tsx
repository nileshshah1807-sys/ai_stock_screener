import Link from "next/link";
import { Hourglass } from "lucide-react";

import { daysLeftLabel, trialStartLine } from "@/lib/billing.mjs";
import { getPlans, getSubscription } from "@/lib/plans";
import { cn } from "@/lib/utils";

/**
 * Shown to someone on the free trial, under the header, in the same inset form
 * as the freshness notice. Quiet until the last two days, then caution-toned.
 * Nobody else sees it: paid, invited and admin accounts have nothing to count.
 */
export function TrialBanner({ days, setUp }: { days: number; setUp?: string | null }) {
  const soon = days <= 2;
  return (
    <div
      role="status"
      className={cn(
        "mx-4 mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-4 py-2.5 text-sm sm:mx-6",
        soon ? "border-caution/30 bg-caution/8 text-caution" : "bg-(--control)",
      )}
    >
      <span className="flex min-w-0 items-start gap-3">
        <Hourglass className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span className="font-medium">
          Free trial: {daysLeftLabel(days)}
          {setUp ? ` · ${setUp}` : ""}
        </span>
      </span>
      <Link prefetch={false}
        href={setUp ? "/account" : "/pricing"}
        className="rounded underline underline-offset-2 hover:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {setUp ? "Manage" : "See the plan"}
      </Link>
    </div>
  );
}

/** The banner for a signed-in trial user: says so when a plan is already set up. */
export async function TrialBannerFor({ days, userId }: { days: number; userId: string }) {
  const subscription = await getSubscription(userId);
  const plans = subscription?.plan_id ? await getPlans() : null;
  const plan = plans?.find((candidate) => candidate.id === subscription?.plan_id) ?? null;
  return <TrialBanner days={days} setUp={trialStartLine(subscription, plan)} />;
}
