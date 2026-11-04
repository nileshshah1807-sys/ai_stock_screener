import type { Metadata } from "next";
import Link from "next/link";

import { LEGAL } from "@/lib/legal";

export const metadata: Metadata = { title: "Terms of Service" };

export default function TermsPage() {
  return (
    <>
      <h1>Terms of Service</h1>
      <p className="text-muted-foreground">Effective {LEGAL.effective}</p>

      <p>
        These terms are an agreement between you and {LEGAL.operator}, {LEGAL.operatorForm}{" "}
        (&ldquo;we&rdquo;, &ldquo;us&rdquo;), for your use of {LEGAL.service} (the
        &ldquo;Service&rdquo;). By signing in or using the Service you accept them. If you do not
        accept them, do not use the Service.
      </p>

      <h2>1. What the Service is</h2>
      <p>
        {LEGAL.service} is a data analytics and research tool for listed equities in India and the
        United States. It shows scores, ranks, technical stages, financial statements, filings and
        earnings-call information computed from public and third-party data.
      </p>
      <p>
        The Service is <strong>not</strong> investment advice, a research report, a recommendation
        or an offer to buy or sell any security. We are not registered with the Securities and
        Exchange Board of India (SEBI) as an Investment Adviser or Research Analyst, and we are not
        a registered investment adviser or broker-dealer in the United States. Read the{" "}
        <Link href="/disclaimer">Disclaimer</Link>, which forms part of these terms.
      </p>

      <h2>2. Who may use it</h2>
      <ul>
        <li>You must be at least 18 years old and able to enter a binding contract.</li>
        <li>
          An account is for one person. Do not share your sign-in link or session with anyone
          else.
        </li>
        <li>
          You are responsible for keeping access to your email account secure, because that is how
          you sign in.
        </li>
      </ul>

      <h2>3. Your decisions are your own</h2>
      <p>
        Anything you do in the market is your decision and at your own risk. Before investing,
        consider your own objectives, finances and risk tolerance, and where appropriate consult a
        SEBI-registered Investment Adviser or other qualified professional. We do not know your
        circumstances and the Service does not take them into account.
      </p>

      <h2>4. Subscriptions and payment</h2>
      <p>
        Where the Service is offered on a paid plan, the price, billing period and what the plan
        includes are shown before you pay. Plans renew automatically at the end of each period
        until you cancel; cancelling stops the next renewal and you keep access until the end of
        the period already paid for. Fees are charged in advance and, except where the law requires
        otherwise or the plan says differently, are not refunded for a partly used period. Prices
        may change for future periods; we will tell you at least 30 days before a change applies to
        you. Taxes are added where applicable.
      </p>

      <h2>5. Acceptable use</h2>
      <p>You agree not to:</p>
      <ul>
        <li>
          copy, scrape, download in bulk, resell, republish or redistribute data or content from
          the Service, except the exports the Service itself offers, for your own personal use;
        </li>
        <li>
          use the Service to give investment advice or recommendations to others, or present its
          output as your own research to clients;
        </li>
        <li>use bots, scripts or automated access, or try to get around access controls;</li>
        <li>reverse engineer the Service or its scoring methods;</li>
        <li>interfere with the Service, its security, or other users.</li>
      </ul>

      <h2>6. Data and accuracy</h2>
      <p>
        Data comes from exchanges, regulators, companies and third-party providers, and is
        processed by automated models. It can be delayed, incomplete or wrong, and a model can
        misread a filing or a call. We do not guarantee that any figure is accurate, complete or
        current. Check anything important against the original source before relying on it.
      </p>

      <h2>7. Intellectual property</h2>
      <p>
        The Service, its software, design, scores and methodology belong to us. Company filings,
        transcripts and recordings belong to their owners and are shown for reference. We give you
        a personal, non-transferable, revocable licence to use the Service under these terms;
        nothing else is licensed to you.
      </p>

      <h2>8. Availability and changes</h2>
      <p>
        We may change, suspend or stop any part of the Service. Scheduled data updates can be late
        or missed. We aim to keep the Service available but do not promise it will be
        uninterrupted or error-free.
      </p>

      <h2>9. Limitation of liability</h2>
      <p>
        To the extent the law allows: the Service is provided &ldquo;as is&rdquo; without
        warranties of any kind; we are not liable for any trading or investment loss, lost profit,
        or indirect or consequential loss arising from your use of the Service or reliance on its
        content; and our total liability to you for any claim is limited to the fees you paid us
        in the 12 months before the claim arose (or INR 1,000 if you paid nothing). Nothing in these
        terms limits liability that cannot be limited by law.
      </p>

      <h2>10. Indemnity</h2>
      <p>
        You agree to compensate us for claims, losses and costs arising from your breach of these
        terms or your misuse of the Service.
      </p>

      <h2>11. Ending your use</h2>
      <p>
        You may stop using the Service and ask us to delete your account at any time. We may
        suspend or end your access if you breach these terms, or if we stop offering the Service;
        if we end a paid plan for a reason other than your breach, we refund the unused part of the
        period.
      </p>

      <h2>12. Changes to these terms</h2>
      <p>
        We may update these terms. We will post the new version here with a new effective date,
        and tell you of material changes in advance. Continuing to use the Service after a change
        takes effect means you accept it.
      </p>

      <h2>13. Law and disputes</h2>
      <p>
        These terms are governed by the laws of India. Courts at {LEGAL.jurisdiction} have
        exclusive jurisdiction, subject to any right you have under consumer protection law to
        bring a claim where you live.
      </p>

      <h2>14. Contact and grievances</h2>
      <p>
        Questions about these terms: {LEGAL.contactEmail}. Grievances: {LEGAL.grievanceOfficer},
        Grievance Officer, {LEGAL.grievanceEmail}, {LEGAL.address}. We acknowledge a grievance
        within 48 hours and aim to resolve it within 15 days.
      </p>
    </>
  );
}
