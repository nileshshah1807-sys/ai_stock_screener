"use client";

import Link from "next/link";
import { useActionState } from "react";
import { Info, Loader2, MailCheck, TriangleAlert } from "lucide-react";

import { CODE_LENGTH } from "@/lib/login-code.mjs";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { requestLoginCode, verifyLoginCode, type CodeState, type LoginState } from "./actions";

const INITIAL: LoginState = { status: "idle" };

/**
 * `notice` is why the visitor landed here -- a spent link, a session that ran
 * out. It is drawn as a note above the field rather than as a field error:
 * nothing they typed was wrong, so the input is not marked invalid for it.
 */
export function LoginForm({ notice, trial = false }: { notice: string | null; trial?: boolean }) {
  // Explicit type arguments: inferring from the initial value widens `status`
  // to string and loses the discriminated union.
  const [state, formAction, pending] = useActionState<LoginState, FormData>(
    requestLoginCode,
    INITIAL,
  );
  const [codeState, codeAction, verifying] = useActionState<CodeState, FormData>(verifyLoginCode, { status: "idle" });

  if (state.status === "sent") {
    return (
      <form action={codeAction} className="animate-rise space-y-4" aria-live="polite">
        <span className="flex size-10 items-center justify-center rounded-full bg-positive/10">
          <MailCheck className="size-5 text-positive" aria-hidden />
        </span>
        <div>
          <p className="text-sm font-medium">Check your inbox</p>
          <p className="mt-1 text-sm text-muted-foreground">{state.message}</p>
          {state.email ? (
            <p className="mt-3 truncate rounded-md bg-(--control) px-4 py-2 text-sm font-medium">{state.email}</p>
          ) : null}
        </div>
        <input type="hidden" name="email" value={state.email ?? ""} />
        <div className="space-y-2">
          <Label htmlFor="code">6-digit code</Label>
          <Input
            id="code"
            name="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9 ]*"
            maxLength={CODE_LENGTH + 3}
            placeholder="123 456"
            required
            autoFocus
            aria-invalid={codeState.status === "error"}
            aria-describedby={codeState.status === "error" ? "code-error" : undefined}
            className="h-10 font-mono tracking-[0.3em]"
          />
        </div>
        {codeState.status === "error" && codeState.message ? (
          <p id="code-error" role="alert" className="flex items-start gap-2 text-sm text-destructive">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            {codeState.message}
          </p>
        ) : null}
        <Button type="submit" className="h-10 w-full" disabled={verifying}>
          {verifying ? (
            <>
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Checking…
            </>
          ) : (
            "Sign in"
          )}
        </Button>
        <p className="text-xs leading-relaxed text-muted-foreground">
          The code works once and expires in 15 minutes. Or open the link in the email and press Continue.{" "}
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="underline underline-offset-2 hover:text-foreground"
          >
            Use a different address or send a new code
          </button>
        </p>
      </form>
    );
  }

  return (
    <form action={formAction} className="space-y-4">
      {notice && state.status === "idle" ? (
        <p
          role="status"
          className="flex items-start gap-2.5 rounded-row bg-(--control) px-4 py-3 text-sm leading-relaxed"
        >
          <Info className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
          {notice}
        </p>
      ) : null}

      <div className="space-y-2">
        <Label htmlFor="email">Email address</Label>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          required
          defaultValue={state.email}
          aria-describedby={state.status === "error" ? "login-error" : undefined}
          aria-invalid={state.status === "error"}
          className="h-10"
        />
      </div>

      {state.status === "error" && state.message ? (
        <p
          id="login-error"
          role="alert"
          className="flex items-start gap-2 text-sm text-destructive"
        >
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          {state.message}
        </p>
      ) : null}

      <Button type="submit" className="h-10 w-full" disabled={pending}>
        {pending ? (
          <>
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Sending code…
          </>
        ) : (
          trial ? "Start free trial" : "Email me a code"
        )}
      </Button>
      <p className="text-center text-xs text-muted-foreground">
        By continuing you agree to the{" "}
        <Link href="/terms" className="underline underline-offset-2 hover:text-foreground">Terms</Link> and{" "}
        <Link href="/privacy" className="underline underline-offset-2 hover:text-foreground">Privacy policy</Link>.
      </p>
    </form>
  );
}
