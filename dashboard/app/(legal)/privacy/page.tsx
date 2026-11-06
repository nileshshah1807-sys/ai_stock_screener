import type { Metadata } from "next";

import { LEGAL } from "@/lib/legal";

export const metadata: Metadata = { title: "Privacy Policy" };

export default function PrivacyPage() {
  return (
    <>
      <h1>Privacy Policy</h1>
      <p className="text-muted-foreground">Effective {LEGAL.effective}</p>

      <p>
        This policy explains what personal data {LEGAL.service} collects, why, and what you can do
        about it. It is written to meet India&rsquo;s Digital Personal Data Protection Act, 2023
        and the Information Technology Act, 2000. {LEGAL.operator} is the Data
        Fiduciary responsible for your data.
      </p>

      <h2>1. What we collect</h2>
      <ul>
        <li>
          <strong>Account:</strong> your email address, used to send your sign-in link and to
          identify your account, and your access level.
        </li>
        <li>
          <strong>What you save:</strong> your watchlists and the stocks in them, and when you
          last read your notifications.
        </li>
        <li>
          <strong>Sign-in session:</strong> cookies that keep you signed in. They are strictly
          necessary and expire when your session does.
        </li>
        <li>
          <strong>Technical logs:</strong> our hosting and database providers record requests
          (IP address, browser, time, page) to run and secure the Service.
        </li>
        <li>
          <strong>Free-trial check:</strong> to give each person one free trial, when you sign in
          we store scrambled (salted, one-way hashed) fingerprints of your IP address, of your
          email address with dots and &ldquo;+&rdquo; tags removed, and of a random device
          identifier kept in a cookie in your browser for about 13 months. We cannot turn them
          back into the original values, and we use them for nothing else. They are deleted with
          your account.
        </li>
        <li>
          <strong>Payment:</strong> when paid plans are offered, payments are handled by our
          payment provider. We receive confirmation of the payment, not your card or bank details.
        </li>
      </ul>
      <p>
        Saved screener views, your light or dark theme, and the grid&rsquo;s scroll position are
        kept in your own browser&rsquo;s storage and are never sent to us.
      </p>
      <p>
        We do not collect your brokerage credentials, your holdings, or any sensitive personal
        data, and we do not use advertising or tracking cookies.
      </p>

      <h2>2. Why we use it</h2>
      <ul>
        <li>to create your account, sign you in and keep it secure;</li>
        <li>to provide the features you use, such as watchlists and notifications;</li>
        <li>to send messages about your account, the Service or your subscription;</li>
        <li>to find and fix faults, and to prevent misuse;</li>
        <li>to meet our legal obligations.</li>
      </ul>
      <p>
        We process your data with your consent, given when you create an account, and for the
        uses the law allows without it, such as meeting a legal obligation. We do not sell your
        data or use it to train AI models.
      </p>

      <h2>3. Who processes it for us</h2>
      <ul>
        <li>Supabase: database, authentication and sign-in emails.</li>
        <li>Vercel: hosting of the website.</li>
        <li>Our payment provider, once paid plans are offered.</li>
      </ul>
      <p>
        They process data only on our instructions. Our database and servers are in Tokyo,
        Japan, so your data is stored outside India. We transfer it only to countries the
        Government of India has not restricted. We may disclose data where the law, a court or a
        regulator requires it.
      </p>

      <h2>4. How long we keep it</h2>
      <p>
        We keep your account data while your account is open. When you delete your account we
        erase it within 30 days, except what the law requires us to keep, such as payment
        records. Technical logs are kept for a limited time by our providers.
      </p>
      <p>
        When an administrator changes or deletes an account, we log the action with that
        account&apos;s email address. The log is kept after the account is deleted.
      </p>

      <h2>5. Your rights</h2>
      <p>You may ask us to:</p>
      <ul>
        <li>tell you what personal data we hold about you and how we use it;</li>
        <li>correct or complete it;</li>
        <li>erase it, and close your account;</li>
        <li>withdraw your consent, which ends your use of the Service;</li>
        <li>
          name someone to exercise these rights for you in the event of your death or incapacity.
        </li>
      </ul>
      <p>
        Write to <a href={`mailto:${LEGAL.grievanceEmail}`}>{LEGAL.grievanceEmail}</a>. We answer within 30 days. If you are not satisfied with
        our answer you may complain to the Data Protection Board of India.
      </p>

      <h2>6. Security</h2>
      <p>
        Data is encrypted in transit, access to the database is restricted by row-level rules so
        each account reads only what it may, and administrative access is limited. No system is
        completely secure; we will tell you and the authorities about a breach as the law
        requires.
      </p>

      <h2>7. Children</h2>
      <p>The Service is for adults only. We do not knowingly collect data from anyone under 18.</p>

      <h2>8. Changes</h2>
      <p>
        We will post any change to this policy here with a new effective date, and tell you
        before a material change applies to you.
      </p>

      <h2>9. Grievance Officer</h2>
      <p>
        {LEGAL.grievanceOfficer}, <a href={`mailto:${LEGAL.grievanceEmail}`}>{LEGAL.grievanceEmail}</a>.
      </p>
    </>
  );
}
