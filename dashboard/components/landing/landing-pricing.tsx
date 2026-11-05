import Link from "next/link";
import { Check } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { PERIOD_LABEL, perMonthLabel, planTitle, priceLabel, savingPercent } from "@/lib/billing.mjs";
import { formatDate } from "@/lib/format";
import { getPlans, type Plan } from "@/lib/plans";
import { cn } from "@/lib/utils";

const INCLUDED = [
  "NSE and US stocks under one subscription",
  "A screener with filters and saved views, and a page for every stock",
  "Quarterly results as companies file them, with a results analysis",
  "Earnings calls: upcoming dates and what management said",
  "Shareholding patterns and company documents for Indian stocks",
  "Watchlists and a bell for new results and calls",
];

/** Plans exactly as the plans table holds them: no amount is written in this file. */
export async function LandingPricing() {
  const plans = await getPlans();
  const saving = savingPercent(
    plans?.find((p) => p.period === "yearly"),
    plans?.find((p) => p.period === "monthly"),
  );

  return (
    <div className="grid gap-10 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      <div className="panel p-6 sm:p-8">
        {plans === null ? (
          <p className="text-sm text-muted-foreground">
            Pricing could not be loaded. See the <Link href="/pricing" className="underline underline-offset-2">pricing page</Link> or try again in a moment.
          </p>
        ) : plans.length === 0 ? (
          <p className="text-sm text-muted-foreground">No plan is on sale right now.</p>
        ) : (
          <ul className="divide-y">
            {plans.map((plan) => (
              <Row key={plan.id} plan={plan} saving={plan.period === "yearly" ? saving : null} />
            ))}
          </ul>
        )}
        <Link href="/login?trial=1" className={cn(buttonVariants({ size: "lg" }), "mt-6 h-11 w-full sm:w-auto")}>
          Start 7-day free trial
        </Link>
        <p className="mt-3 text-xs text-muted-foreground">Payments are taken by Razorpay. Full refund within 7 days of a payment.</p>
      </div>
      <div>
        <h3 className="text-lead font-semibold">Everything is included</h3>
        <ul className="mt-4 space-y-3 text-sm">
          {INCLUDED.map((item) => (
            <li key={item} className="flex items-start gap-2.5">
              <Check className="mt-0.5 size-4 shrink-0 text-positive" aria-hidden />
              {item}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function Row({ plan, saving }: { plan: Plan; saving: number | null }) {
  const period = PERIOD_LABEL[plan.period] ?? plan.period;
  const headline = plan.offer ? plan.offer.amount_paise : plan.amount_paise;
  return (
    <li className="py-5 first:pt-0 last:pb-0">
      <p className="flex flex-wrap items-center gap-x-2 text-lead font-semibold">
        {planTitle(plan)}
        {plan.offer ? <span className="rounded-md bg-brand-soft px-2 py-0.5 text-xs font-medium text-brand">{plan.offer.name}</span> : null}
      </p>
      <p className="mt-1 flex flex-wrap items-baseline gap-x-2 tabular-nums">
        <span className="text-display">{priceLabel(headline)}</span>
        {plan.offer ? (
          <s className="text-muted-foreground" aria-label={`regular price ${priceLabel(plan.amount_paise)}`}>
            {priceLabel(plan.amount_paise)}
          </s>
        ) : null}
        <span className="text-sm text-muted-foreground">
          {plan.offer ? `for the first ${period}` : `per ${period}`}
        </span>
      </p>
      {plan.offer ? (
        <p className="mt-1 text-xs text-muted-foreground tabular-nums">
          With UPI Autopay{plan.offer.ends_at ? `, until ${formatDate(plan.offer.ends_at)} or while places last` : ", while places last"}. Then {priceLabel(plan.amount_paise)} per {period}.
        </p>
      ) : null}
      {saving ? (
        <p className="mt-1 text-xs text-muted-foreground tabular-nums">About {perMonthLabel(plan)} a month, {saving}% less than paying monthly.</p>
      ) : null}
    </li>
  );
}
