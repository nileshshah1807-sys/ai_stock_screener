"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { trialName } from "@/lib/billing.mjs";

import { LoginForm } from "./login-form";

type PanelProps = { trialDays: number; sessionLabel: string };

/** The sign-in panel for this URL's ?error and ?trial, read in the browser so the page stays static. */
export function LoginPanel(props: PanelProps) {
  const params = useSearchParams();
  return <LoginPanelView {...props} errorCode={params.get("error")} trial={params.get("trial") === "1"} />;
}

/**
 * ?trial=1 is the sign-up path: the same code form, framed as the start of a
 * free trial. A new address gets an account; a known one just signs in.
 */
export function LoginPanelView({
  trialDays,
  sessionLabel,
  errorCode,
  trial,
}: PanelProps & { errorCode: string | null; trial: boolean }) {
  // Each case names what actually happened. "Expired or already used" is by far
  // the most common, and it is worth saying that a link can be spent before it
  // is clicked: mail providers routinely prefetch URLs to scan them, which
  // consumes a single-use token and makes the real click look broken.
  const errorMessage =
    errorCode === "session_expired"
      ? `You were signed out because that sign-in was more than ${sessionLabel} old. Request a new code to carry on.`
      : errorCode === "expired"
      ? "That link had already been used or has expired. Sign-in links and codes work once and last 15 minutes. Request a new code below."
      : errorCode === "denied"
        ? "That sign-in link was rejected. It may have been issued for a different address, or access may have been revoked."
        : errorCode === "invalid_link"
          ? "That sign-in link could not be verified. Request a new one."
          : errorCode === "missing_code"
            ? "That link was incomplete — it arrived without a sign-in token. Request a new one."
            : null;

  return (
    <>
      <div className="panel animate-rise p-6 sm:p-8">
        <h1 className="text-heading font-semibold">{trial ? `Start your ${trialName(trialDays)}` : "Sign in"}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {trial
            ? "Full access to both markets, no card needed. Enter your email and we\u2019ll send you a 6-digit code."
            : "Enter your email and we\u2019ll send you a 6-digit code. No password needed."}
        </p>

        <div className="mt-6">
          <LoginForm notice={errorMessage} trial={trial} />
        </div>
      </div>

      <p className="mt-6 text-center text-xs leading-relaxed text-muted-foreground">
        {trial ? "Already have an account? " : "New here? "}
        <Link href={trial ? "/login" : "/login?trial=1"} className="underline underline-offset-2 hover:text-foreground">
          {trial ? "Sign in" : `Start your ${trialName(trialDays)}`}
        </Link>
        <br />
        Data for research and education, not investment advice.
      </p>
    </>
  );
}
