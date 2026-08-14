"use client";

import { useActionState } from "react";
import { CheckCircle2, Loader2, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { requestMagicLink, type LoginState } from "./actions";

const INITIAL: LoginState = { status: "idle" };

export function LoginForm({ initialError }: { initialError: string | null }) {
  // Explicit type arguments: inferring from the initial value widens `status`
  // to string and loses the discriminated union.
  const [state, formAction, pending] = useActionState<LoginState, FormData>(
    requestMagicLink,
    initialError
      ? { status: "error", message: initialError }
      : INITIAL,
  );

  if (state.status === "sent") {
    return (
      <div
        className="panel animate-rise p-5"
        role="status"
        aria-live="polite"
      >
        <CheckCircle2 className="size-5 text-positive" aria-hidden />
        <p className="mt-2.5 text-sm font-medium">Check your inbox</p>
        <p className="mt-1 text-sm text-muted-foreground">{state.message}</p>
        <p className="mt-3 text-xs text-muted-foreground">
          The link expires in one hour and can be used once.
        </p>
      </div>
    );
  }

  return (
    <form action={formAction} className="space-y-4">
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
