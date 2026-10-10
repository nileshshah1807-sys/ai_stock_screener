"use client";

import { useActionState } from "react";
import { Info, Loader2, MailCheck, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { requestMagicLink, type LoginState } from "./actions";

const INITIAL: LoginState = { status: "idle" };

/**
 * `notice` is why the visitor landed here -- a spent link, a session that ran
 * out. It is drawn as a note above the field rather than as a field error:
 * nothing they typed was wrong, so the input is not marked invalid for it.
 */
export function LoginForm({ notice }: { notice: string | null }) {
  // Explicit type arguments: inferring from the initial value widens `status`
  // to string and loses the discriminated union.
  const [state, formAction, pending] = useActionState<LoginState, FormData>(
    requestMagicLink,
    INITIAL,
  );

  if (state.status === "sent") {
    return (
      <div className="animate-rise" role="status" aria-live="polite">
        <span className="flex size-10 items-center justify-center rounded-full bg-positive/10">
          <MailCheck className="size-5 text-positive" aria-hidden />
        </span>
        <p className="mt-4 text-sm font-medium">Check your inbox</p>
        <p className="mt-1 text-sm text-muted-foreground">{state.message}</p>
        {state.email ? (
          <p className="mt-3 truncate rounded-full bg-(--control) px-4 py-2 text-sm font-medium">
            {state.email}
          </p>
        ) : null}
        <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
          The link works once and expires in one hour. Open it in this browser.
        </p>
      </div>
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
          className="h-11"
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

      <Button type="submit" className="h-11 w-full" disabled={pending}>
        {pending ? (
          <>
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Sending link…
          </>
        ) : (
          "Email me a sign-in link"
        )}
      </Button>
    </form>
  );
}
