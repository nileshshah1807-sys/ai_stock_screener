import type { Metadata } from "next";

import { BrandMark } from "@/components/brand-mark";
import { sessionMaxAgeSeconds } from "@/lib/session-policy.mjs";

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
    errorCode === "session_expired"
      ? `You were signed out because that sign-in was more than ${sessionLifetimeLabel()} old. Request a new link to carry on.`
      : errorCode === "expired"
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
        {/* The same mark-in-a-disc and wordmark as the app header, so the door
            and the room behind it are visibly the same product. */}
        <div className="mb-6 flex animate-rise items-center justify-center gap-2.5">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
            <BrandMark className="size-5" />
          </span>
          <span className="text-lead font-semibold tracking-[-0.011em]">
            Winnow
          </span>
        </div>

        <div className="panel animate-rise p-6 sm:p-8">
          <h1 className="text-heading font-semibold">Sign in</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Enter your email and we&rsquo;ll send you a link. No password
            needed.
          </p>

          <div className="mt-6">
            <LoginForm notice={errorMessage} />
          </div>
        </div>

        <p className="mt-6 text-center text-xs leading-relaxed text-muted-foreground">
          Private research dashboard, by invitation only.
          <br />
          Research model output, not investment advice.
        </p>
      </div>
    </main>
  );
}

/** "7 days", "12 hours" -- the configured lifetime in the largest unit that divides it. */
function sessionLifetimeLabel(): string {
  const hours = sessionMaxAgeSeconds() / 3600;
  const [count, unit] =
    hours >= 24 && hours % 24 === 0 ? [hours / 24, "day"] : [hours, "hour"];
  return `${Number(count.toFixed(1))} ${unit}${count === 1 ? "" : "s"}`;
}
