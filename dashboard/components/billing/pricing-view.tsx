import Link from "next/link";
import { Check } from "lucide-react";

import { CheckoutButton } from "@/components/billing/checkout-button";
import { buttonVariants } from "@/components/ui/button";
import { PERIOD_LABEL, currentPlanId, lapseReason, perMonthLabel, planTitle, priceLabel, savingPercent } from "@/lib/billing.mjs";
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
  past_due: ["Your last payment did not go through", "Open your profile to see where your plan stands."],
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
    : ["Pricing", "One subscription covers both markets. Every plan includes everything below."];

  const permanent = kind === "admin" || kind === "allowlist";
  const current = currentPlanId(subscription);
  // Someone with time left on a trial sets the plan up now and is first charged
  // when the trial ends; anyone else is charged at once.
  const trialEnds = !lapsed && !current && kind === "trial" ? subscription?.trial_ends_at : null;

  const saving = savingPercent(
    plans?.find((plan) => plan.period === "yearly"),
    plans?.find((plan) => plan.period === "monthly"),
  );

  return (
    <>
      <h1 className="text-heading font-semibold">{headline}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{lead}</p>

      {permanent ? (
        <p role="status" className="mt-5 rounded-row bg-(--control) px-4 py-3 text-sm">
          Your account already has full access, so there is nothing to buy.
        </p>
      ) : null}

      {plans === null ? (
        <p className="panel mt-6 p-6 text-sm text-muted-foreground">Pricing could not be loaded. Try again in a moment.</p>
      ) : plans.length === 0 ? (
        <p className="panel mt-6 p-6 text-sm text-muted-foreground">No plan is on sale right now.</p>
      ) : (
        <ul aria-label="Plans" className="mt-6 grid gap-4 sm:grid-cols-2">
          {plans.map((plan) => (
            <PlanCard
              key={plan.id}
              plan={plan}
              saving={plan.period === "yearly" ? saving : null}
              isCurrent={plan.id === current}
              action={permanent ? null : <PlanAction plan={plan} email={email} subscription={subscription} current={current} trialEnds={trialEnds} />}
            />
          ))}
        </ul>
      )}

      {trialEnds ? (
        <p className="mt-3 text-sm text-muted-foreground">Nothing is charged until your trial ends on {formatDate(trialEnds)}.</p>
      ) : null}

      <section aria-labelledby="included-heading" className="panel mt-6 p-6 sm:p-8">
        <h2 id="included-heading" className="text-sm font-semibold">
          Both plans include
        </h2>
        <ul className="mt-3 grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
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

function PlanCard({ plan, saving, isCurrent, action }: { plan: Plan; saving: number | null; isCurrent: boolean; action: React.ReactNode }) {
  const period = PERIOD_LABEL[plan.period] ?? plan.period;
  const shown = plan.offer?.amount_paise ?? plan.amount_paise;
  return (
    <li className={cn("panel flex flex-col p-6", isCurrent && "ring-2 ring-primary")}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <h2 className="text-lead font-semibold">{planTitle(plan)}</h2>
        {isCurrent ? (
          <span className="rounded-md bg-primary px-2 py-0.5 text-xs font-medium text-primary-foreground">Current plan</span>
        ) : saving ? (
          <span className="rounded-md bg-positive/10 px-2 py-0.5 text-xs font-medium text-positive">Best value</span>
        ) : null}
      </div>

      <p className="mt-4 tabular-nums">
        <span className="text-heading font-semibold">{priceLabel(shown)}</span>{" "}
        <span className="text-sm text-muted-foreground">per {period}</span>
        {plan.offer ? (
          <>
            {" "}
            <s className="text-sm text-muted-foreground" aria-label={`regular price ${priceLabel(plan.amount_paise)}`}>
              {priceLabel(plan.amount_paise)}
            </s>
          </>
        ) : null}
      </p>
      {plan.offer ? (
        <p className="mt-2 rounded-row bg-(--control) px-3 py-2 text-xs leading-relaxed tabular-nums">
          <span className="font-medium">{plan.offer.name}: first {period} only, with UPI Autopay.</span>{" "}
          {plan.offer.ends_at ? `Until ${formatDate(plan.offer.ends_at)} or while places last. ` : ""}Then {priceLabel(plan.amount_paise)} per {period}.
        </p>
      ) : null}

      <dl className="mt-4 space-y-2 border-t pt-4 text-sm">
        <Row label="Billed" value={plan.period === "yearly" ? "Once a year" : "Every month"} />
        <Row label="Works out to" value={`${perMonthLabel(plan)} a month`} />
        <Row label="Compared with monthly" value={saving ? `${saving}% less` : plan.period === "monthly" ? "Month to month" : "-"} />
      </dl>

      <div className="mt-auto pt-6">{action}</div>
    </li>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium tabular-nums">{value}</dd>
    </div>
  );
}

function PlanAction({
  plan,
  email,
  subscription,
  current,
  trialEnds,
}: {
  plan: Plan;
  email: string | null;
  subscription: Subscription | null;
  current: string | null;
  trialEnds: string | null | undefined;
}) {
  const full = "h-10 w-full";
  if (!email) {
    return (
      <Link href="/login?trial=1" className={cn(buttonVariants(), full)}>
        Start your 7-day free trial
      </Link>
    );
  }
  if (current) {
    return plan.id === current ? (
      <Link href="/account" className={cn(buttonVariants({ variant: "outline" }), full)}>
        View in your profile
      </Link>
    ) : (
      <Link href="/account#switch" className={cn(buttonVariants({ variant: "outline" }), full)}>
        Switch to {planTitle(plan).toLowerCase()}
      </Link>
    );
  }
  // A failed payment is fixed from the profile; starting a second subscription is refused.
  if (subscription?.status === "past_due") {
    return (
      <Link href="/account" className={cn(buttonVariants({ variant: "outline" }), full)}>
        Open your profile
      </Link>
    );
  }
  return <CheckoutButton planId={plan.id} email={email} brand={LEGAL.service} label={trialEnds ? "Subscribe, pay after trial" : "Subscribe"} fullWidth />;
}
