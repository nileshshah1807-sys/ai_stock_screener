import { notFound } from "next/navigation";

import { AccountView } from "@/components/billing/account-view";
import { PaymentList, type PaymentRow, type PaymentsState } from "@/components/billing/payment-history";
import { PricingView } from "@/components/billing/pricing-view";
import type { Plan, Subscription } from "@/lib/plans";

/**
 * Development only: the pricing and account pages in each state, from made-up
 * rows, so every state can be looked at without a database or a payment.
 * /billing-preview?view=pricing|account&payments=rows|none|loading|error&name=none&state=signedout|trial|setup|lapsed|active|past_due|cancelled
 * The plans below are placeholders for the picture, not prices; &offer=closed hides the early-bird price.
 */
const PLAN: Plan = {
  id: "preview_plan",
  name: "Yearly",
  amount_paise: 99900,
  offer_amount_paise: 69900,
  period: "yearly",
  offer: { name: "Early bird", amount_paise: 69900, ends_at: "2026-12-31T18:29:59Z" },
};
const MONTHLY: Plan = { id: "preview_monthly", name: "Monthly", amount_paise: 12900, period: "monthly" };
const DAY = 86_400_000;
const iso = (days: number) => new Date(Date.now() + days * DAY).toISOString();

const SUBSCRIPTIONS: Record<string, { kind: string; row: Subscription | null }> = {
  signedout: { kind: "", row: null },
  trial: { kind: "trial", row: { plan_id: null, status: "trialing", trial_ends_at: iso(5), current_period_end: null } },
  setup: { kind: "trial", row: { plan_id: PLAN.id, offer_applied: true, status: "trialing", trial_ends_at: iso(5), current_period_end: null } },
  lapsed: { kind: "lapsed", row: { plan_id: null, status: "expired", trial_ends_at: iso(-1), current_period_end: null } },
  active: { kind: "paid", row: { plan_id: PLAN.id, status: "active", trial_ends_at: null, current_period_end: iso(27) } },
  past_due: { kind: "lapsed", row: { plan_id: PLAN.id, status: "past_due", trial_ends_at: null, current_period_end: iso(-2) } },
  cancelled: { kind: "lapsed", row: { plan_id: PLAN.id, status: "cancelled", trial_ends_at: null, current_period_end: iso(-2) } },
};

const iso0 = (days: number) => new Date(Date.now() - days * DAY).toISOString();
const PAID: PaymentRow[] = [
  { id: "a", date: iso0(3), paise: 69900, currency: "INR", method: "Visa ending 4242", status: "paid", receiptUrl: "https://rzp.io/i/preview" },
  { id: "b", date: iso0(33), paise: 12900, currency: "INR", method: "UPI", status: "refunded", receiptUrl: "https://rzp.io/i/preview" },
  { id: "c", date: iso0(63), paise: 12900, currency: "INR", method: "Bank autopay", status: "failed", receiptUrl: null },
];
const PAYMENTS: Record<string, PaymentsState> = {
  rows: { status: "ready", rows: PAID },
  none: { status: "ready", rows: [] },
  loading: { status: "loading" },
  error: { status: "error" },
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
    <AccountView email={email ?? "reader@example.com"} name={params.name === "none" ? null : "Priya Shah"} createdAt={iso0(40)} payments={<PaymentList state={PAYMENTS[String(params.payments)] ?? (state.row?.plan_id ? PAYMENTS.rows : PAYMENTS.none)} />} kind={state.kind || "trial"} subscription={state.row} plan={plan} plans={[PLAN, MONTHLY]} welcome={params.welcome === "1"} />
  ) : (
    <PricingView plans={params.plans === "none" ? [] : [params.offer === "closed" ? { ...PLAN, offer: null } : PLAN, MONTHLY]} email={email} kind={state.kind || undefined} subscription={state.row} />
  );
}
