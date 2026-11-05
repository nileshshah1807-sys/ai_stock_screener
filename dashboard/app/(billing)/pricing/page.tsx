import type { Metadata } from "next";

import { PricingView } from "@/components/billing/pricing-view";
import { getSession } from "@/lib/auth";
import { getPlans, getSubscription } from "@/lib/plans";

export const metadata: Metadata = { title: "Pricing" };

export default async function PricingPage() {
  const [session, plans] = await Promise.all([getSession(), getPlans()]);
  const subscription = session ? await getSubscription(session.id) : null;
  return <PricingView plans={plans} email={session?.email ?? null} kind={session?.access.kind} subscription={subscription} />;
}
