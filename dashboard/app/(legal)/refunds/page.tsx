import type { Metadata } from "next";
import Link from "next/link";

import { trialName } from "@/lib/billing.mjs";
import { LEGAL } from "@/lib/legal";
import { getTrialDays } from "@/lib/trial-days";

export const metadata: Metadata = {
  title: "Refunds & cancellation",
  robots: { index: true, follow: true },
  alternates: { canonical: "/refunds" },
};

// The trial length is the only live figure: rebuilt every five minutes, never per request.
export const revalidate = 300;

export default async function RefundsPage() {
  const trialDays = await getTrialDays();
  return (
    <>
      <h1>Refunds &amp; cancellation</h1>
      <p className="text-muted-foreground">Effective {LEGAL.effective}</p>

      <h2>1. The free trial</h2>
      <p>
        A new account starts with a {trialName(trialDays)} of full access. No card is needed to start it,
        and nothing is charged during it. If you subscribe during the trial, the trial ends and
        your plan starts at once: the first payment is taken that day.
      </p>

      <h2>2. Cancelling</h2>
      <p>
        You can cancel from your <Link href="/account">account</Link> at any time. Your plan stays
        active until the end of the period you have paid for, and is not renewed after it.
      </p>

      <h2>3. Refunds</h2>
      <p>
        If you ask within 7 days of a payment, we refund it in full. This holds for a first
        payment and for a renewal, on the monthly plan and the yearly plan alike. The 7 days run
        from the day of the payment, including a first payment made during the free trial.
      </p>
      <p>
        To ask, email <a href={`mailto:${LEGAL.contactEmail}`}>{LEGAL.contactEmail}</a> from the address on your account and say which payment
        you mean. We send the refund back to the method you paid with, through Razorpay. It
        usually reaches you in 5 to 7 working days. Your access ends when the refund is processed.
      </p>
      <p>
        After 7 days a payment is not refunded. You can still{" "}
        <Link href="/account">cancel</Link> at any time: that stops the next renewal, and your
        access runs to the end of the period you have paid for.
      </p>
      <p>
        If you were charged in error, or twice, write to the same address and we will put it
        right.
      </p>

      <h2>4. Payments</h2>
      <p>
        Payments are taken by Razorpay. We do not see or store your card details. See the{" "}
        <Link href="/terms">Terms</Link> and <Link href="/privacy">Privacy</Link> pages for the
        rest.
      </p>
    </>
  );
}
