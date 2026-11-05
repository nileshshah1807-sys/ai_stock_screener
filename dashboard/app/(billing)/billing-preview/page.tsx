import { notFound } from "next/navigation";

import { AccountView } from "@/components/billing/account-view";
import { PricingView } from "@/components/billing/pricing-view";
import type { Plan, Subscription } from "@/lib/plans";

/**
 * Development only: the pricing and account pages in each state, from made-up
 * rows, so every state can be looked at without a database or a payment.
 * /billing-preview?view=pricing|account&state=signedout|trial|setup|lapsed|active|past_due|cancelled
 * The plan below is a placeholder for the picture, not a price.
 */
const PLAN: Plan = { id: "preview_plan", name: "Standard", amount_paise: 49900, period: "monthly" };
const DAY = 86_400_000;
const iso = (days: number) => new Date(Date.now() + days * DAY).toISOString();

const SUBSCRIPTIONS: Record<string, { kind: string; row: Subscription | null }> = {
  signedout: { kind: "", row: null },
  trial: { kind: "trial", row: { plan_id: null, status: "trialing", trial_ends_at: iso(5), current_period_end: null } },
  setup: { kind: "trial", row: { plan_id: PLAN.id, status: "trialing", trial_ends_at: iso(5), current_period_end: null } },
  lapsed: { kind: "lapsed", row: { plan_id: null, status: "expired", trial_ends_at: iso(-1), current_period_end: null } },
  active: { kind: "paid", row: { plan_id: PLAN.id, status: "active", trial_ends_at: null, current_period_end: iso(27) } },
  past_due: { kind: "lapsed", row: { plan_id: PLAN.id, status: "past_due", trial_ends_at: null, current_period_end: iso(-2) } },
  cancelled: { kind: "lapsed", row: { plan_id: PLAN.id, status: "cancelled", trial_ends_at: null, current_period_end: iso(-2) } },
};

export default async function BillingPreview({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const params = await searchParams;
  const state = SUBSCRIPTIONS[String(params.state)] ?? SUBSCRIPTIONS.trial;
  const email = params.state === "signedout" ? null : "reader@example.com";
  const plan = state.row?.plan_id ? PLAN : null;

  return params.view === "account" ? (
    <AccountView email={email ?? "reader@example.com"} kind={state.kind || "trial"} subscription={state.row} plan={plan} welcome={params.welcome === "1"} />
  ) : (
    <PricingView plans={params.plans === "none" ? [] : [PLAN]} email={email} kind={state.kind || undefined} subscription={state.row} />
  );
}
