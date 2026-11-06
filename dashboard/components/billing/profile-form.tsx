"use client";

import { useActionState, useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { Check, Loader2, TriangleAlert } from "lucide-react";

import { saveDisplayName, type NameState } from "@/app/(billing)/account/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NAME_MAX } from "@/lib/display-name.mjs";

const IDLE: NameState = { status: "idle" };

/**
 * The display name, saved to the person's own auth metadata. The email is shown
 * but not editable here: changing it is a sign-in change, not a profile one.
 * Save is available only when the field differs from what is stored.
 */
export function ProfileForm({ name, email, memberSince }: { name: string; email: string; memberSince: string }) {
  const [state, action, pending] = useActionState(saveDisplayName, IDLE);
  const [value, setValue] = useState(name);
  const tick = useRef<SVGSVGElement>(null);
  const changed = value.trim() !== name.trim();

  // The stored name changes only after a save; the field follows it (adjusting state during render, not in an effect).
  const [seen, setSeen] = useState(name);
  if (seen !== name) {
    setSeen(name);
    setValue(name);
  }

  useEffect(() => {
    if (state.status !== "saved" || !tick.current) return;
    const mm = gsap.matchMedia();
    mm.add("(prefers-reduced-motion: no-preference)", () => {
      gsap.from(tick.current, { scale: 0, duration: 0.4, ease: "back.out(2)" });
    });
    return () => mm.revert();
  }, [state]);

  return (
    <div className="mt-4 space-y-5 text-sm">
      <form action={action} className="space-y-2">
        <label htmlFor="display-name" className="block text-muted-foreground">
          Display name
        </label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            id="display-name"
            name="name"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            maxLength={NAME_MAX + 20}
            autoComplete="name"
            placeholder="How should we address you?"
            aria-describedby="display-name-status"
            aria-invalid={state.status === "error" || undefined}
            className="h-10 sm:max-w-sm"
          />
          <Button type="submit" className="h-10 sm:w-24" disabled={pending || !changed}>
            {pending ? (
              <>
                <Loader2 className="size-4 animate-spin" aria-hidden />
                Saving
              </>
            ) : (
              "Save"
            )}
          </Button>
        </div>
        <div id="display-name-status" aria-live="polite">
          {state.status === "saved" && !changed ? (
            <p className="flex items-center gap-1.5 text-brand">
              <Check ref={tick} className="size-4" aria-hidden />
              {state.message}
            </p>
          ) : state.status === "error" ? (
            <p role="alert" className="flex items-start gap-1.5 text-destructive">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
              {state.message}
            </p>
          ) : null}
        </div>
      </form>

      <dl className="grid gap-x-6 gap-y-4 border-t pt-5 sm:grid-cols-2">
        <div className="min-w-0">
          <dt className="text-muted-foreground">Email</dt>
          <dd className="mt-0.5 truncate font-medium">{email}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Member since</dt>
          <dd className="mt-0.5 font-medium tabular-nums">{memberSince}</dd>
        </div>
      </dl>
    </div>
  );
}
