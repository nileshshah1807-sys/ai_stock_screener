import { BillingFrame } from "@/components/billing/billing-frame";
import { PricingView } from "@/components/billing/pricing-view";
import { getPlans } from "@/lib/plans";
import { getTrialDays } from "@/lib/trial-days";

import { pricingMetadata } from "../(billing)/pricing/metadata";

/*
 * /pricing for a visitor with no session: proxy.ts rewrites to this copy, which is static and
 * refreshed every 5 minutes, so a visit renders nothing on the server (the Free plan allows 10 ms
 * of CPU). Outside the (billing) group, whose layout reads the session; it is what
 * app/(billing)/pricing shows anyone with no session.
 */
export const revalidate = 300;
export const metadata = pricingMetadata;

export default async function StaticPricingPage() {
  const [plans, trialDays] = await Promise.all([getPlans(), getTrialDays()]);
  return (
    <BillingFrame session={null}>
      <PricingView plans={plans} email={null} name={null} kind={undefined} subscription={null} trialDays={trialDays} />
    </BillingFrame>
  );
}
