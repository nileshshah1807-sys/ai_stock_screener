import type { Metadata } from "next";

import { PricingView } from "@/components/billing/pricing-view";
import { getSession } from "@/lib/auth";
import { getPlans, getSubscription } from "@/lib/plans";
import { getTrialDays } from "@/lib/trial-days";

export const metadata: Metadata = {
  title: "Pricing",
  description: "Cupel plans and prices: a yearly and a monthly plan covering NSE and US stocks, a screener, quarterly results and earnings calls. Data for research and education, not investment advice.",
  robots: { index: true, follow: true },
  alternates: { canonical: "/pricing" },
};

export default async function PricingPage() {
  const [session, plans, trialDays] = await Promise.all([getSession(), getPlans(), getTrialDays()]);
  const subscription = session ? await getSubscription(session.id) : null;
  return <PricingView plans={plans} email={session?.email ?? null} kind={session?.access.kind} subscription={subscription} trialDays={trialDays} />;
}
