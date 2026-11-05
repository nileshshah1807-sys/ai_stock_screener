import Link from "next/link";

import { AccountActions } from "@/components/billing/account-actions";
import { buttonVariants } from "@/components/ui/button";
import { PERIOD_LABEL, currentPlanId, isSetUp, planSummary, planTitle, priceLabel } from "@/lib/billing.mjs";
import { formatDate } from "@/lib/format";
import { LEGAL } from "@/lib/legal";
import type { Plan, Subscription } from "@/lib/plans";
import { signOut } from "@/app/login/actions";
import { cn } from "@/lib/utils";

/** "reader@example.com" -> "RE"; the avatar is initials, never a photo. */
function initials(email: string) {
  const letters = email.split("@")[0].split(/[^a-zA-Z0-9]+/).filter(Boolean);
  return (letters.length > 1 ? letters[0][0] + letters[1][0] : (letters[0] ?? "?").slice(0, 2)).toUpperCase();
}

/** The account page's content, from data its caller has already read. */
export function AccountView({
  email,
  kind,
  subscription,
  plan,
  plans,
  welcome,
}: {
  email: string;
  kind: string;
  subscription: Subscription | null;
  /** The plan the subscription row names, when it names one. */
  plan: Plan | null;
  /** Every plan on sale, to offer the one the person is not on. */
  plans: Plan[] | null;
  welcome: boolean;
}) {
  const summary = planSummary({ kind, subscription, plan }, formatDate);
  const setUp = isSetUp(subscription);
  const permanent = kind === "admin" || kind === "allowlist";
  const showSubscribe = !setUp && !permanent && subscription?.status !== "past_due";
  const current = currentPlanId(subscription);
  const other = current ? (plans?.find((candidate) => candidate.id !== current) ?? null) : null;
  const price = plan ? `${priceLabel(plan.amount_paise)} per ${PERIOD_LABEL[plan.period] ?? plan.period}` : null;

  return (
    <>
      <header className="flex items-center gap-4">
        <span
          aria-hidden
          className="flex size-14 shrink-0 items-center justify-center rounded-full bg-primary text-lead font-semibold text-primary-foreground"
        >
          {initials(email)}
        </span>
        <div className="min-w-0">
          <h1 className="text-heading font-semibold">Profile</h1>
          <p className="truncate text-sm text-muted-foreground">{email}</p>
        </div>
      </header>

      {welcome ? (
        <p role="status" className="mt-5 rounded-row bg-(--control) px-4 py-3 text-sm">
          Thank you. Your plan is set up.
        </p>
      ) : null}

      <section aria-labelledby="plan-heading" className="panel mt-6 p-6 sm:p-8">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div>
            <h2 id="plan-heading" className="text-sm text-muted-foreground">
              Your plan
            </h2>
            <p className="mt-1 text-lead font-semibold">{summary.title}</p>
            {price ? <p className="text-sm text-muted-foreground tabular-nums">{price}</p> : null}
          </div>
          <span className="rounded-md bg-(--control) px-2.5 py-1 text-xs font-medium">{summary.status}</span>
        </div>

        <p className="mt-5 text-sm leading-relaxed">{summary.detail}</p>

        {summary.nextCharge ? (
          <dl className="mt-5 grid grid-cols-2 gap-4 border-t pt-5 text-sm">
            <div>
              <dt className="text-muted-foreground">Next charge</dt>
              <dd className="mt-0.5 font-medium tabular-nums">{formatDate(summary.nextCharge.date)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Amount</dt>
              <dd className="mt-0.5 font-medium tabular-nums">{priceLabel(summary.nextCharge.paise)}</dd>
            </div>
          </dl>
        ) : null}

        {showSubscribe ? (
          <Link href="/pricing" className={cn(buttonVariants(), "mt-6 h-10 w-full sm:w-auto")}>
            {kind === "lapsed" || subscription?.status === "cancelled" ? "Subscribe" : "Choose a plan"}
          </Link>
        ) : null}
      </section>

      {other ? (
        <section id="switch" aria-labelledby="switch-heading" className="panel mt-4 scroll-mt-6 p-6 sm:p-8">
          <h2 id="switch-heading" className="text-sm font-semibold">
            Switch plan
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            You can move to the {planTitle(other).toLowerCase()} ({priceLabel(other.amount_paise)} per {PERIOD_LABEL[other.period] ?? other.period}). Cancel
            your current plan below; it stays active until {summary.nextCharge ? formatDate(summary.nextCharge.date) : "the end of the period"}, and nothing
            more is charged. Then choose the new plan on the pricing page.
          </p>
          <Link href="/pricing" className={cn(buttonVariants({ variant: "outline" }), "mt-3 h-10 w-full sm:w-auto")}>
            Compare plans
          </Link>
        </section>
      ) : null}

      <section aria-label="Cancel or delete" className="panel mt-4 p-6 sm:p-8">
        <AccountActions canCancel={setUp && subscription?.status !== "cancelled"} inTrial={subscription?.status === "trialing"} contactEmail={LEGAL.contactEmail} />
      </section>

      <form action={signOut} className="mt-6">
        <button type="submit" className={cn(buttonVariants({ variant: "outline" }), "h-10")}>
          Sign out
        </button>
      </form>
    </>
  );
}
