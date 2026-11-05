import Link from "next/link";

import { AccountActions } from "@/components/billing/account-actions";
import { buttonVariants } from "@/components/ui/button";
import { PERIOD_LABEL, isSetUp, priceLabel } from "@/lib/plan-access.mjs";
import { formatDate } from "@/lib/format";
import { LEGAL } from "@/lib/legal";
import type { Plan, Subscription } from "@/lib/plans";
import { signOut } from "@/app/login/actions";
import { cn } from "@/lib/utils";

/** The account page's content, from data its caller has already read. */
export function AccountView({
  email,
  kind,
  subscription,
  plan,
  welcome,
}: {
  email: string;
  kind: string;
  subscription: Subscription | null;
  plan: Plan | null;
  welcome: boolean;
}) {
  const summary = describe(kind, subscription, plan);
  const setUp = isSetUp(subscription);
  const showSubscribe = !setUp && kind !== "admin" && kind !== "allowlist";

  return (
    <>
      <h1 className="text-heading font-semibold">Account</h1>

      {welcome ? (
        <p role="status" className="mt-4 rounded-row bg-(--control) px-4 py-3 text-sm">
          Thank you. Your plan is set up.
        </p>
      ) : null}

      <section aria-label="Your plan" className="panel mt-6 p-6 sm:p-8">
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-3 text-sm">
          <dt className="text-muted-foreground">Email</dt>
          <dd className="min-w-0 break-words font-medium">{email}</dd>
          <dt className="text-muted-foreground">Plan</dt>
          <dd className="font-medium">{summary.plan}</dd>
          <dt className="text-muted-foreground">Status</dt>
          <dd className="font-medium">{summary.status}</dd>
          {summary.next ? (
            <>
              <dt className="text-muted-foreground">{summary.next[0]}</dt>
              <dd className="font-medium tabular-nums">{summary.next[1]}</dd>
            </>
          ) : null}
        </dl>

        {showSubscribe ? (
          <Link href="/pricing" className={cn(buttonVariants(), "mt-6 h-10 w-full sm:w-auto")}>
            {kind === "lapsed" ? "Subscribe" : "See the plan"}
          </Link>
        ) : null}
      </section>

      <section aria-label="Cancel or delete" className="panel mt-4 p-6 sm:p-8">
        <AccountActions canCancel={setUp && subscription?.status !== "cancelled"} inTrial={subscription?.status === "trialing"} contactEmail={LEGAL.contactEmail} />
      </section>

      <form action={signOut} className="mt-6">
        <button
          type="submit"
          className="rounded text-sm text-muted-foreground underline underline-offset-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Sign out
        </button>
      </form>
    </>
  );
}

/** The plan, status and next date as sentences, from the token's kind and the subscription row. */
function describe(kind: string, subscription: Subscription | null, plan: Plan | null) {
  if (kind === "admin") return { plan: "Administrator", status: "Full access", next: null };
  if (kind === "allowlist") return { plan: "Invited account", status: "Full access, no expiry", next: null };

  const planName = plan ? `${plan.name} (${priceLabel(plan.amount_paise)} per ${PERIOD_LABEL[plan.period] ?? plan.period})` : null;
  switch (subscription?.status) {
    case "active":
      return { plan: planName ?? "Subscribed", status: "Active", next: ["Renews", formatDate(subscription.current_period_end)] as const };
    case "trialing":
      return subscription.plan_id
        ? { plan: planName ?? "Subscribed", status: "Free trial, plan set up", next: ["First charge", formatDate(subscription.trial_ends_at)] as const }
        : { plan: "Free trial", status: "Free trial", next: ["Trial ends", formatDate(subscription.trial_ends_at)] as const };
    case "past_due":
      return { plan: planName ?? "Subscribed", status: "Last payment did not go through", next: null };
    case "cancelled":
      return {
        plan: planName ?? "Subscribed",
        status: kind === "lapsed" ? "Cancelled" : "Cancelled, active until the end of the period",
        next: kind === "lapsed" ? null : (["Access until", formatDate(subscription.current_period_end)] as const),
      };
    default:
      return { plan: "None", status: kind === "lapsed" ? "Free trial ended" : "No plan", next: null };
  }
}
