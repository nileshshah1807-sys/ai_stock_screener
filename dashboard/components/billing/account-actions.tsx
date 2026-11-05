"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Loader2, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";

type Props = {
  /** Cancelling is offered only while a plan is set up. */
  canCancel: boolean;
  /** Still in the free trial: cancelling stops the plan before any charge. */
  inTrial: boolean;
  /** Where the person can write if a request fails. */
  contactEmail: string;
};

/**
 * Two requests that cannot be undone from this page, each asked for twice: the
 * first press shows what will happen, the second does it. Not a modal -- the
 * explanation sits where the button was.
 */
export function AccountActions({ canCancel, inTrial, contactEmail }: Props) {
  return (
    <div className="divide-y">
      {canCancel ? (
        <Action
          title="Cancel your plan"
          explain={
            inTrial
              ? "Your plan is cancelled now and the first charge will not be made. Nothing has been charged."
              : "Your plan stays active until the end of the period you have paid for, then stops. You will not be charged again."
          }
          button="Cancel plan"
          confirm={inTrial ? "Yes, cancel my plan" : "Yes, cancel at the end of the period"}
          endpoint="/api/billing/cancel"
          done={inTrial ? "Your plan is cancelled. You will not be charged." : "Your plan is cancelled and will not renew."}
          contactEmail={contactEmail}
        />
      ) : null}
      <Action
        title="Delete your account"
        explain="This asks us to delete your account and the data tied to it, such as your watchlists. If you have a plan, cancel it first. We will confirm by email."
        button="Request deletion"
        confirm="Yes, request deletion"
        endpoint="/api/account/delete-request"
        done="Deletion requested. We will email you when it is done."
        contactEmail={contactEmail}
      />
    </div>
  );
}

type Phase = "idle" | "asking" | "working" | "done";

function Action({
  title,
  explain,
  button,
  confirm,
  endpoint,
  done,
  contactEmail,
}: {
  title: string;
  explain: string;
  button: string;
  confirm: string;
  endpoint: string;
  done: string;
  contactEmail: string;
}) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setPhase("working");
    setError(null);
    try {
      const response = await fetch(endpoint, { method: "POST" });
      if (!response.ok) throw new Error(String(response.status));
      setPhase("done");
      router.refresh();
    } catch {
      setError(`That did not go through. Try again, or write to ${contactEmail}.`);
      setPhase("asking");
    }
  }

  return (
    <div className="py-5 first:pt-0 last:pb-0">
      <h3 className="text-sm font-semibold">{title}</h3>
      {phase === "done" ? (
        <p role="status" className="mt-2 text-sm text-muted-foreground">
          {done}
        </p>
      ) : (
        <>
          <p className="mt-1 text-sm text-muted-foreground">{explain}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {phase === "idle" ? (
              <Button type="button" variant="outline" className="h-10" onClick={() => setPhase("asking")}>
                {button}
              </Button>
            ) : (
              <>
                <Button type="button" variant="destructive" className="h-10" disabled={phase === "working"} onClick={run}>
                  {phase === "working" ? (
                    <>
                      <Loader2 className="size-4 animate-spin" aria-hidden />
                      Working{"…"}
                    </>
                  ) : (
                    confirm
                  )}
                </Button>
                <Button type="button" variant="ghost" className="h-10" disabled={phase === "working"} onClick={() => setPhase("idle")}>
                  Keep it
                </Button>
              </>
            )}
          </div>
          <div aria-live="polite">
            {error ? (
              <p role="alert" className="mt-3 flex items-start gap-2 text-sm text-destructive">
                <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                {error}
              </p>
            ) : null}
          </div>
        </>
      )}
    </div>
  );
}
