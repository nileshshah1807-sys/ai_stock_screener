import Link from "next/link";

import { PricingPlans } from "@/components/billing/pricing-plans";
import { getTrialDays } from "@/lib/trial-days";
import { planPanels } from "@/components/billing/pricing-view";
import { getPlans } from "@/lib/plans";

/**
 * The landing's pricing section: the same plan card as /pricing (toggle, price
 * count, early-bird countdown, comparison), built by the same function, shown to a
 * visitor who is signed out -- its button starts the free trial. Plans are read as
 * the plans table holds them: no amount is written in this file.
 */
export async function LandingPricing() {
  const [plans, trialDays] = await Promise.all([getPlans(), getTrialDays()]);

  if (plans === null) {
    return (
      <p className="panel p-6 text-sm text-muted-foreground">
        Pricing could not be loaded. See the <Link href="/pricing" className="underline underline-offset-2">pricing page</Link> or try again in a moment.
      </p>
    );
  }
  if (plans.length === 0) return <p className="panel p-6 text-sm text-muted-foreground">No plan is on sale right now.</p>;

  const { panels, initialId } = planPanels(plans, { email: null, kind: undefined, subscription: null, trialDays });
  return (
    <>
      <PricingPlans panels={panels} initialId={initialId} embedded />
      <p className="mt-4 text-xs text-muted-foreground">Payments are taken by Razorpay. Full refund within 7 days of a payment.</p>
    </>
  );
}
