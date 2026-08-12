import type { Metadata } from "next";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  // Next.js 16: searchParams is a Promise.
  const params = await searchParams;
  const errorCode = typeof params.error === "string" ? params.error : null;

  const errorMessage =
    errorCode === "invalid_link"
      ? "That sign-in link has expired or was already used. Request a new one."
      : errorCode === "missing_code"
        ? "That link was incomplete. Request a new one."
        : null;

  return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8">
          <h1 className="font-mono text-lg font-semibold tracking-tight">
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
