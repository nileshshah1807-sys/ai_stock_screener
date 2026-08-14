import type { Metadata } from "next";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  // Next.js 16: searchParams is a Promise.
  const params = await searchParams;
  const errorCode = typeof params.error === "string" ? params.error : null;

  // Each case names what actually happened. "Expired or already used" is by far
  // the most common, and it is worth saying that a link can be spent before it
  // is clicked: mail providers routinely prefetch URLs to scan them, which
  // consumes a single-use token and makes the real click look broken.
  const errorMessage =
    errorCode === "expired"
      ? "That link had already been used or has expired. Sign-in links work once, and some mail providers open them automatically to scan for spam — which can use one up before you click it. Request a new one below."
      : errorCode === "denied"
        ? "That sign-in link was rejected. It may have been issued for a different address, or access may have been revoked."
        : errorCode === "invalid_link"
          ? "That sign-in link could not be verified. Request a new one."
          : errorCode === "missing_code"
            ? "That link was incomplete — it arrived without a sign-in token. Request a new one."
            : null;

  return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 animate-rise">
          <h1 className="font-mono text-heading font-semibold tracking-tight">
            NSE Screener
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Private research dashboard. Sign-in is by invitation.
          </p>
        </div>

        <LoginForm initialError={errorMessage} />

        <p className="mt-8 text-xs leading-relaxed text-muted-foreground">
          Research model output, not investment advice. Point-in-time
          out-of-sample validation is pending.
        </p>
      </div>
    </main>
  );
}
