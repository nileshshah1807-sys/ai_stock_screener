import Link from "next/link";
import { Check } from "lucide-react";

import { CheckoutButton } from "@/components/billing/checkout-button";
import { buttonVariants } from "@/components/ui/button";
import { PERIOD_LABEL, isSetUp, lapseReason, perMonthLabel, priceLabel, savingPercent } from "@/lib/plan-access.mjs";
import { formatDate } from "@/lib/format";
import { LEGAL } from "@/lib/legal";
import type { Plan, Subscription } from "@/lib/plans";
import { cn } from "@/lib/utils";

/** What a subscription covers. No price, rating or return is stated here. */
const INCLUDED = [
  "NSE and US stocks under one subscription",
  "A screener with filters and saved views, and a page for every stock",
  "Quarterly results as companies file them, with a results analysis",
  "Earnings calls: upcoming dates and what management said",
  "Shareholding patterns and company documents for Indian stocks",
  "Watchlists and a bell for new results and calls",
];

const LAPSED_HEADLINE = {
  trial_ended: ["Your free trial has ended", "Subscribe to carry on where you left off."],
  cancelled: ["Your subscription has ended", "Subscribe again to get access back."],
  past_due: ["Your last payment did not go through", "Subscribe again to get access back."],
} as const;


/** The pricing page's content, from data its caller has already read. */
export function PricingView({
  plans,
  email,
  kind,
  subscription,
}: {
  plans: Plan[] | null;
  email: string | null;
  kind: string | undefined;
  subscription: Subscription | null;
}) {
  const lapsed = kind === "lapsed";
  const [headline, lead] = lapsed
    ? LAPSED_HEADLINE[lapseReason(subscription?.status)]
    : ["Pricing", "One subscription covers both markets."];

  // Someone with time left on a trial sets the plan up now and is first charged
  // when the trial ends; anyone else is charged at once.
  const setUp = isSetUp(subscription);
  const trialEnds = !lapsed && !setUp && kind === "trial" ? subscription?.trial_ends_at : null;

  const saving = savingPercent(
    plans?.find((plan) => plan.period === "yearly"),
    plans?.find((plan) => plan.period === "monthly"),
  );

  return (
    <>
      <h1 className="text-heading font-semibold">{headline}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{lead}</p>

      <section aria-label="Plans" className="panel mt-6 p-6 sm:p-8">
        {plans === null ? (
          <p className="text-sm text-muted-foreground">Pricing could not be loaded. Try again in a moment.</p>
        ) : plans.length === 0 ? (
          <p className="text-sm text-muted-foreground">No plan is on sale right now.</p>
        ) : (
          <ul className="divide-y">
            {plans.map((plan) => (
              <PlanRow key={plan.id} plan={plan} saving={plan.period === "yearly" ? saving : null} email={email} kind={kind} setUp={setUp} trialEnds={trialEnds} />
            ))}
          </ul>
        )}

        <h2 className="mt-8 text-sm font-semibold">What you get</h2>
        <ul className="mt-3 space-y-2 text-sm">
          {INCLUDED.map((item) => (
            <li key={item} className="flex items-start gap-2.5">
              <Check className="mt-0.5 size-4 shrink-0 text-positive" aria-hidden />
              {item}
            </li>
          ))}
        </ul>
      </section>

      <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
        Payments are taken by Razorpay. By subscribing you accept the{" "}
        <Link href="/terms" className="underline underline-offset-2 hover:text-foreground">Terms</Link>, the{" "}
        <Link href="/privacy" className="underline underline-offset-2 hover:text-foreground">Privacy policy</Link> and the{" "}
        <Link href="/refunds" className="underline underline-offset-2 hover:text-foreground">Refund policy</Link> of {LEGAL.service}.
      </p>
    </>
  );
}

function PlanRow({
  plan,
  saving,
  email,
  kind,
  setUp,
  trialEnds,
}: {
  plan: Plan;
  /** Whole percent the yearly plan saves against the monthly one, when it does. */
  saving: number | null;
  email: string | null;
  kind: string | undefined;
  setUp: boolean;
  trialEnds: string | null | undefined;
}) {
  const period = PERIOD_LABEL[plan.period] ?? plan.period;
  return (
    <li className="flex flex-col gap-4 py-5 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="flex flex-wrap items-center gap-x-2 text-lead font-semibold">
          {plan.name}
          {saving ? (
            <span className="rounded-md bg-positive/10 px-2 py-0.5 text-xs font-medium text-positive">Best value</span>
          ) : null}
        </p>
        {plan.offer ? (
          <>
            <p className="mt-0.5 text-sm text-muted-foreground tabular-nums">
              <span className="text-base font-semibold text-foreground">{priceLabel(plan.offer.amount_paise)}</span>{" "}
              <s aria-label={`regular price ${priceLabel(plan.amount_paise)}`}>{priceLabel(plan.amount_paise)}</s> for the first {period}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground tabular-nums">
              {plan.offer.name}
              {plan.offer.ends_at ? `, until ${formatDate(plan.offer.ends_at)} or while places last` : ""}. Then{" "}
              {priceLabel(plan.amount_paise)} per {period}.
            </p>
          </>
        ) : (
          <p className="mt-0.5 text-sm text-muted-foreground tabular-nums">
            <span className="text-base font-semibold text-foreground">{priceLabel(plan.amount_paise)}</span> per {period}
          </p>
        )}
        {saving ? (
          <p className="mt-0.5 text-xs text-muted-foreground tabular-nums">
            About {perMonthLabel(plan)} a month, {saving}% less than paying monthly.
          </p>
        ) : null}
        {trialEnds ? (
          <p className="mt-1 text-xs text-muted-foreground">Nothing is charged until your trial ends on {formatDate(trialEnds)}.</p>
        ) : null}
      </div>
      <div className="sm:text-right">
        <PlanAction planId={plan.id} email={email} kind={kind} setUp={setUp} />
      </div>
    </li>
  );
}

function PlanAction({ planId, email, kind, setUp }: { planId: string; email: string | null; kind: string | undefined; setUp: boolean }) {
  const brand = LEGAL.service;
  if (!email) {
    return (
      <Link href="/login?trial=1" className={cn(buttonVariants(), "h-10 w-full sm:w-auto")}>
        Start your 7-day free trial
      </Link>
    );
  }
  if (kind === "paid" || setUp) {
    return (
      <Link href="/account" className={cn(buttonVariants({ variant: "outline" }), "h-10 w-full sm:w-auto")}>
        You are subscribed
      </Link>
    );
  }
  if (kind === "admin" || kind === "allowlist") {
    return <p className="text-sm text-muted-foreground">Your account already has full access.</p>;
  }
  return <CheckoutButton planId={planId} email={email} brand={brand} label="Subscribe" />;
}
