import type { Metadata } from "next";
import Link from "next/link";

import { LEGAL } from "@/lib/legal";

export const metadata: Metadata = { title: "Refunds & cancellation" };

/*
 * shortcut: the refund terms in section 3 are a placeholder for the operator to
 * decide; the payment gateway asks for this page before it goes live. Have a
 * lawyer read it with the other three.
 */
export default function RefundsPage() {
  return (
    <>
      <h1>Refunds &amp; cancellation</h1>
      <p className="text-muted-foreground">Effective {LEGAL.effective}</p>

      <h2>1. The free trial</h2>
      <p>
        A new account starts with a 7-day free trial of full access. No card is needed to start it,
        and nothing is charged during it. If you set up a plan during the trial, the first charge
        is made when the trial ends.
      </p>

      <h2>2. Cancelling</h2>
      <p>
        You can cancel from your <Link href="/account">account</Link> at any time. Your plan stays
        active until the end of the period you have paid for, and is not renewed after it.
      </p>

      <h2>3. Refunds</h2>
      <p>[Refund terms: to be set by the operator before launch.]</p>
      <p>
        If you were charged in error, or twice, write to {LEGAL.contactEmail} and we will put it
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
