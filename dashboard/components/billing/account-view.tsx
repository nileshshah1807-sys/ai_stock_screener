import Link from "next/link";

import { AccountActions } from "@/components/billing/account-actions";
import { AccountMotion } from "@/components/billing/account-motion";
import { ProfileForm } from "@/components/billing/profile-form";
import { buttonVariants } from "@/components/ui/button";
import { PERIOD_LABEL, currentPlanId, isSetUp, planSummary, planTitle, priceLabel } from "@/lib/billing.mjs";
import { initialsOf, shownName } from "@/lib/display-name.mjs";
import { formatDate } from "@/lib/format";
import { LEGAL } from "@/lib/legal";
import type { Plan, Subscription } from "@/lib/plans";
import { signOut } from "@/app/login/actions";
import { cn } from "@/lib/utils";

/** The account page's content, from data its caller has already read. */
export function AccountView({
  email,
  name,
  createdAt,
  payments,
  kind,
  subscription,
  plan,
  plans,
  welcome,
}: {
  email: string;
  /** The display name saved in the person's auth metadata, if they set one. */
  name: string | null;
  /** When the account was created (auth created_at). */
  createdAt: string | null;
  /** The payment history, drawn by the caller: the live list on the page, fixtures in the preview. */
  payments: React.ReactNode;
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
    <AccountMotion>
      <header data-arrive className="flex items-center gap-4">
        <span
          aria-hidden
          className="flex size-14 shrink-0 items-center justify-center rounded-full bg-primary text-lead font-semibold text-primary-foreground"
        >
          {initialsOf(name, email)}
        </span>
        <div className="min-w-0">
          <h1 className="truncate text-heading font-semibold">{shownName(name, email)}</h1>
          <p className="truncate text-sm text-muted-foreground">{email}</p>
        </div>
      </header>

      {welcome ? (
        <p role="status" data-arrive className="mt-5 rounded-row bg-brand-soft px-4 py-3 text-sm">
          Thank you. Your plan is set up.
        </p>
      ) : null}

      <section aria-labelledby="profile-heading" data-arrive className="panel mt-6 p-6 sm:p-8">
        <h2 id="profile-heading" className="text-sm font-semibold">
          Profile
        </h2>
        <ProfileForm name={name ?? ""} email={email} memberSince={formatDate(createdAt)} />
      </section>

      <section aria-labelledby="plan-heading" data-arrive className="panel mt-4 p-6 sm:p-8">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div>
            <h2 id="plan-heading" className="text-sm text-muted-foreground">
              Your plan
            </h2>
            <p className="mt-1 text-lead font-semibold">{summary.title}</p>
            {price ? <p className="text-sm text-muted-foreground tabular-nums">{price}</p> : null}
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-md bg-(--control) px-2.5 py-1 text-xs font-medium">
            {summary.status === "Active" || summary.status === "Full access" ? <span aria-hidden className="size-1.5 rounded-full bg-brand" /> : null}
            {summary.status}
          </span>
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

      {!permanent ? (
        <section aria-labelledby="payments-heading" data-arrive className="panel mt-4 p-6 sm:p-8">
          <h2 id="payments-heading" className="text-sm font-semibold">
            Payment history
          </h2>
          {payments}
        </section>
      ) : null}

      {other ? (
        <section id="switch" aria-labelledby="switch-heading" data-arrive className="panel mt-4 scroll-mt-6 p-6 sm:p-8">
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

      <section aria-label="Cancel or delete" data-arrive className="panel mt-4 p-6 sm:p-8">
        <AccountActions canCancel={setUp && subscription?.status !== "cancelled"} inTrial={subscription?.status === "trialing"} contactEmail={LEGAL.contactEmail} />
      </section>

      <div data-arrive className="mt-6 flex flex-wrap gap-3">
        <form action={signOut}>
          <button type="submit" className={cn(buttonVariants({ variant: "outline" }), "h-10")}>
            Sign out
          </button>
        </form>
        {kind === "admin" ? (
          <Link href="/admin" className={cn(buttonVariants({ variant: "outline" }), "h-10")}>
            Admin: users
          </Link>
        ) : null}
      </div>
    </AccountMotion>
  );
}
