import type { Metadata } from "next";
import Link from "next/link";

import { SupportForm } from "@/components/support/support-form";
import { getSession } from "@/lib/auth";
import { LEGAL } from "@/lib/legal";
import { supportConfigured } from "@/lib/support.mjs";
import { createClient } from "@/lib/supabase/server";

export const metadata: Metadata = {
  title: "Help & Support",
  description: "Answers about Cupel's data, update times, trial, billing and refunds, and a form to write to us.",
  robots: { index: true, follow: true },
  alternates: { canonical: "/help" },
};

const LINK = "underline underline-offset-2";

const FAQ: [string, React.ReactNode][] = [
  ["Where does the data come from?", "Prices and most company figures come from Yahoo Finance. US annual statements come from SEC EDGAR. NSE quarterly results, shareholding and deals are read from the exchange's own filings. Earnings-call text comes from the filed transcript, or the call's recording until it is filed."],
  ["When is it updated?", "The screener is rebuilt once a day after each market closes. Live prices refresh every five minutes during the session, and quarterly results appear within minutes of the company filing them."],
  ["How do the free trial and billing work?", <>A new account gets a free trial with full access and no card. After it you pick a plan on the <Link href="/pricing" className={LINK}>pricing page</Link>; payments are handled by Razorpay.</>],
  ["How do I cancel or get a refund?", <>Cancel any time from <Link href="/account" className={LINK}>your account</Link>; access runs to the end of the paid period. Refund rules are on the <Link href="/refunds" className={LINK}>Refunds page</Link>.</>],
  ["Why can I not see buy or sell ratings?", "Ratings are shown to administrators only. Everyone else sees the underlying data, scores and filters. Nothing here is investment advice."],
];

export default async function HelpPage() {
  const session = await getSession();
  const claims = session ? (await (await createClient()).auth.getClaims()).data?.claims : null;
  const name = typeof claims?.user_metadata?.full_name === "string" ? claims.user_metadata.full_name : "";

  return (
    <div className="grid gap-10">
      <header>
        <h1 className="text-title">Help &amp; Support</h1>
        <p className="mt-2 text-sm text-muted-foreground">Quick answers first; if they do not cover it, write to us.</p>
      </header>

      <section aria-labelledby="faq" className="grid gap-2">
        <h2 id="faq" className="text-heading">Common questions</h2>
        {FAQ.map(([question, answer]) => (
          <details key={question} className="rounded-md border bg-card px-4 py-3 text-sm">
            <summary className="cursor-pointer font-medium">{question}</summary>
            <p className="mt-2 leading-relaxed text-muted-foreground">{answer}</p>
          </details>
        ))}
      </section>

      <section aria-labelledby="contact" className="grid gap-4">
        <h2 id="contact" className="text-heading">Write to us</h2>
        {session && supportConfigured(process.env) ? (
          <SupportForm email={session.email} name={name} contactEmail={LEGAL.contactEmail} />
        ) : (
          <p className="text-sm">
            Write to <a href={`mailto:${LEGAL.contactEmail}`} className={LINK}>{LEGAL.contactEmail}</a> and we will reply by email.
            {session ? null : <> Signed-in members can also use a form here.</>}
          </p>
        )}
      </section>
    </div>
  );
}
