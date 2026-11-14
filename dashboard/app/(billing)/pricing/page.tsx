import { PricingView } from "@/components/billing/pricing-view";
import { getSession } from "@/lib/auth";
import { getPlans, getSubscription } from "@/lib/plans";
import { createClient } from "@/lib/supabase/server";
import { getTrialDays } from "@/lib/trial-days";

import { pricingMetadata } from "./metadata";

export const metadata = pricingMetadata;

export default async function PricingPage() {
  const [session, plans, trialDays] = await Promise.all([getSession(), getPlans(), getTrialDays()]);
  const subscription = session ? await getSubscription(session.id) : null;
  // The saved profile name, as checkout reads it (the token's user_metadata).
  const claims = session ? (await (await createClient()).auth.getClaims()).data?.claims : null;
  const name = typeof claims?.user_metadata?.full_name === "string" ? claims.user_metadata.full_name : null;
  return <PricingView plans={plans} email={session?.email ?? null} name={name} kind={session?.access.kind} subscription={subscription} trialDays={trialDays} />;
}
