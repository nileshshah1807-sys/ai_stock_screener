import Link from "next/link";

import { CheckoutButton } from "@/components/billing/checkout-button";
import { PricingPlans, type PlanPanel } from "@/components/billing/pricing-plans";
import { Reveal } from "@/components/motion";
import { buttonVariants } from "@/components/ui/button";
import { PERIOD_LABEL, currentPlanId, lapseReason, perMonthLabel, planTitle, priceLabel, savingPercent } from "@/lib/billing.mjs";
import { formatDate } from "@/lib/format";
import { LEGAL } from "@/lib/legal";
import type { Plan, Subscription } from "@/lib/plans";
import { cn } from "@/lib/utils";

const LAPSED_HEADLINE = {
  trial_ended: ["Your free trial has ended", "Subscribe to carry on where you left off."],
  cancelled: ["Your subscription has ended", "Subscribe again to get access back."],
  past_due: ["Your last payment did not go through", "Open your profile to see where your plan stands."],
} as const;

type Who = { email: string | null; kind: string | undefined; subscription: Subscription | null };

/**
 * The plan panels as words and buttons, for whoever is looking: the /pricing page
 * and the landing's pricing section build theirs here, so the two cannot differ.
 * Signed out (email null) the action is "Start your 7-day free trial".
 */
export function planPanels(plans: Plan[], { email, kind, subscription }: Who) {
  const lapsed = kind === "lapsed";
  const permanent = kind === "admin" || kind === "allowlist";
  const current = currentPlanId(subscription);
  // Buying during the trial ends it: the first charge is made now.
  const endsTrial = !lapsed && !current && kind === "trial";

  const saving = savingPercent(
    plans?.find((plan) => plan.period === "yearly"),
    plans?.find((plan) => plan.period === "monthly"),
  );

  const panels: PlanPanel[] = plans.map((plan) => {
    const period = PERIOD_LABEL[plan.period] ?? plan.period;
    const planSaving = plan.period === "yearly" ? saving : null;
    return {
      plan,
      isCurrent: plan.id === current,
      badge: planSaving ? "value" : null,
      note: plan.offer
        ? `${plan.offer.name}: first ${period} only, with UPI Autopay. ${plan.offer.ends_at ? `Until ${formatDate(plan.offer.ends_at)} or while places last. ` : ""}Then ${priceLabel(plan.amount_paise)} per ${period}.`
        : null,
      facts: [
        { label: "Billed", value: plan.period === "yearly" ? "Once a year" : "Every month" },
        { label: "Works out to", value: `${perMonthLabel(plan)} a month` },
        { label: "Compared with monthly", value: planSaving ? `${planSaving}% less` : plan.period === "monthly" ? "Month to month" : "-" },
      ],
      action: permanent ? null : <PlanAction plan={plan} email={email} subscription={subscription} current={current} />,
    };
  });
  // Opens on the plan someone holds, else the one that is better value, else the first.
  const initialId = current && panels.some((p) => p.plan.id === current) ? current : (panels.find((p) => p.badge === "value") ?? panels[0])?.plan.id;
  return { panels, initialId, endsTrial, permanent };
}

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
  const { panels, initialId, endsTrial, permanent } = planPanels(plans ?? [], { email, kind, subscription });

  return (
    <>
      <Reveal selector="[data-hero]" stagger={0.08}>
        <h1 data-hero className="text-title font-semibold">{headline}</h1>
        <p data-hero className="mt-1.5 text-sm text-muted-foreground">{lead}</p>
      </Reveal>

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
        <div className="mt-6">
          <PricingPlans
            panels={panels}
            initialId={initialId}
            note={endsTrial ? <p className="text-sm text-muted-foreground">Subscribing ends your free trial and starts your plan today. Full refund within 7 days of a payment.</p> : null}
          />
        </div>
      )}

      <p className="mt-6 text-xs leading-relaxed text-muted-foreground">
        Payments are taken by Razorpay. By subscribing you accept the{" "}
        <Link href="/terms" className="underline underline-offset-2 hover:text-foreground">Terms</Link>, the{" "}
        <Link href="/privacy" className="underline underline-offset-2 hover:text-foreground">Privacy policy</Link> and the{" "}
        <Link href="/refunds" className="underline underline-offset-2 hover:text-foreground">Refund policy</Link> of {LEGAL.service}.
      </p>
    </>
  );
}

function PlanAction({
  plan,
  email,
  subscription,
  current,
}: {
  plan: Plan;
  email: string | null;
  subscription: Subscription | null;
  current: string | null;
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
  return <CheckoutButton planId={plan.id} email={email} brand={LEGAL.service} label="Subscribe" fullWidth />;
}
