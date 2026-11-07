"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useRef, useState, useSyncExternalStore } from "react";
import { Loader2, TriangleAlert } from "lucide-react";

import { saveDisplayName } from "@/app/(billing)/account/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { checkoutRestriction, isSetUp } from "@/lib/billing.mjs";
import { invoiceNameProblem } from "@/lib/display-name.mjs";
import { createClient } from "@/lib/supabase/client";

const CHECKOUT_SRC = "https://checkout.razorpay.com/v1/checkout.js";
const POLL_EVERY_MS = 2000;
const POLL_FOR_MS = 90_000;

type RazorpayOptions = {
  key: string;
  subscription_id: string;
  name: string;
  description: string;
  prefill: { email: string; name?: string };
  method?: Record<string, boolean>;
  config?: unknown;
  handler: (response: { razorpay_payment_id?: string; razorpay_subscription_id?: string; razorpay_signature?: string }) => void;
  modal: { ondismiss: () => void };
};
declare global {
  interface Window {
    Razorpay?: new (options: RazorpayOptions) => { open: () => void };
  }
}

type Created = {
  subscription_id: string;
  key_id: string;
  customer_name?: string;
  plan: { id: string; name: string; amount_paise: number; period: string };
  offer_applied?: boolean;
  offer_unavailable?: boolean;
};

const ERRORS: Record<string, string> = {
  no_active_plan: "No plan is on sale right now. Try again later.",
  razorpay_error: "The payment provider could not start checkout. Try again in a minute.",
  billing_not_configured: "Payments are not switched on yet.",
};

/** Razorpay's checkout script is loaded when first needed, not on every page. */
function loadCheckout(): Promise<boolean> {
  if (window.Razorpay) return Promise.resolve(true);
  return new Promise((resolve) => {
    const script = document.createElement("script");
    script.src = CHECKOUT_SRC;
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.head.appendChild(script);
  });
}

/**
 * One checkout at a time on the page, across every plan's button: a second
 * press while one is starting or open could otherwise create two subscriptions.
 */
let inFlight = false;
const watchers = new Set<() => void>();
function setInFlight(value: boolean) {
  inFlight = value;
  watchers.forEach((notify) => notify());
}
function useInFlight() {
  return useSyncExternalStore(
    (notify) => {
      watchers.add(notify);
      return () => watchers.delete(notify);
    },
    () => inFlight,
    () => false,
  );
}

type Phase = "idle" | "starting" | "paying" | "confirming" | "slow";

/**
 * Opens Razorpay Checkout for the plan.
 *
 * The checkout's own success callback is not proof of payment: the browser sends
 * its signed result to /api/billing/confirm, which verifies it and writes the
 * subscription (the webhook is the fallback), so the button waits for that row to read as set up,
 * then refreshes the session so the token's plan claim catches up, and only
 * then moves on. If the row has not changed after 90 seconds it says so and
 * leaves the person to come back; their payment is not lost.
 */
export function CheckoutButton({
  planId,
  email,
  savedName = null,
  brand,
  label,
  fullWidth = false,
}: {
  planId: string;
  email: string;
  /** The profile name, if any. Without a valid one the buyer is asked for it: every invoice names them. */
  savedName?: string | null;
  brand: string;
  label: string;
  fullWidth?: boolean;
}) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<{ text: string; link?: boolean } | null>(null);
  const [offerGone, setOfferGone] = useState(false);
  const locked = useInFlight();
  const nameId = useId();
  const needsName = invoiceNameProblem(savedName) !== null;
  const [name, setName] = useState(savedName ?? "");
  const [touched, setTouched] = useState(false);
  const nameField = useRef<HTMLInputElement>(null);
  const nameProblem = needsName ? invoiceNameProblem(name) : null;

  async function waitForSubscription(proof: object) {
    const supabase = createClient();
    // Ask the server to verify the payment and write the subscription now; the
    // webhook stays the fallback if this fails or Razorpay is not yet settled.
    // AbortController, not AbortSignal.timeout (missing in older Safari/WebViews); nothing here may skip the poll.
    try {
      const abort = new AbortController();
      const timer = setTimeout(() => abort.abort(), 15_000);
      await fetch("/api/billing/confirm", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(proof),
        signal: abort.signal,
      }).finally(() => clearTimeout(timer));
    } catch {
      // the poll and the webhook still grant access
    }
    const deadline = Date.now() + POLL_FOR_MS;
    while (Date.now() < deadline) {
      const { data } = await supabase.from("subscriptions").select("status, plan_id").maybeSingle();
      if (isSetUp(data)) {
        await supabase.auth.refreshSession();
        router.push("/account?welcome=1");
        router.refresh();
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, POLL_EVERY_MS));
    }
    setPhase("slow");
    setInFlight(false);
  }

  async function start() {
    if (inFlight) return;
    if (nameProblem) {
      // No dead button: say what is missing and put the cursor there.
      setTouched(true);
      nameField.current?.focus();
      return;
    }
    setInFlight(true);
    setError(null);
    setPhase("starting");
    try {
      if (needsName) {
        // Saved to the profile like the account page does, then the token is refreshed so create-subscription reads it.
        const form = new FormData();
        form.set("name", name);
        const saved = await saveDisplayName({ status: "idle" }, form);
        if (saved.status === "error") {
          setError({ text: saved.message ?? "Your name did not save. Try again." });
          setPhase("idle");
          setInFlight(false);
          return;
        }
        const { error: refreshError } = await createClient().auth.refreshSession();
        if (refreshError) {
          // Without the new token the invoice would carry the email: stop and let them retry.
          setError({ text: "Could not save your name. Try again." });
          setPhase("idle");
          setInFlight(false);
          return;
        }
      }
      const [response, loaded] = await Promise.all([
        fetch("/api/billing/create-subscription", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ plan_id: planId }),
        }),
        loadCheckout(),
      ]);
      const body = (await response.json().catch(() => ({}))) as Partial<Created> & { error?: string };
      // A signed-out or expired session is redirected to /login by the proxy
      // (HTML, status 200 after the follow), so a redirect counts as a 401.
      if (response.status === 401 || response.redirected) {
        router.push("/login?trial=1");
        return;
      }
      if (response.status === 409) {
        setError({ text: "You already have a subscription.", link: true });
        setPhase("idle");
        setInFlight(false);
        return;
      }
      if (!response.ok || !body.subscription_id || !body.key_id || !body.plan) {
        setError({ text: ERRORS[body.error ?? ""] ?? "Checkout could not start. Try again." });
        setPhase("idle");
        setInFlight(false);
        return;
      }
      if (!loaded || !window.Razorpay) {
        setError({ text: "The payment window could not load. Check your connection and try again." });
        setPhase("idle");
        setInFlight(false);
        return;
      }
      setOfferGone(Boolean(body.offer_unavailable));
      setPhase("paying");
      new window.Razorpay({
        key: body.key_id,
        subscription_id: body.subscription_id,
        name: brand,
        description: body.plan.name,
        prefill: { email, name: body.customer_name },
        ...checkoutRestriction(body.offer_applied),
        handler: (proof) => {
          setPhase("confirming");
          void waitForSubscription(proof);
        },
        modal: {
          ondismiss: () => {
            setPhase((now) => (now === "paying" ? "idle" : now));
            setInFlight(false);
          },
        },
      }).open();
    } catch {
      setError({ text: "Checkout could not start. Check your connection and try again." });
      setPhase("idle");
      setInFlight(false);
    }
  }

  const working = phase === "starting" || phase === "confirming";
  return (
    <div className="space-y-3">
      {needsName ? (
        <div className="space-y-1.5">
          <label htmlFor={nameId} className="block text-sm text-muted-foreground">
            Name for your invoice
          </label>
          <Input
            id={nameId}
            ref={nameField}
            value={name}
            onChange={(event) => setName(event.target.value)}
            onBlur={() => setTouched(true)}
            autoComplete="name"
            required
            aria-invalid={(touched && nameProblem !== null) || undefined}
            aria-describedby={`${nameId}-problem`}
            className="h-10"
          />
          <p id={`${nameId}-problem`} aria-live="polite" className="text-xs text-destructive">
            {touched && nameProblem ? nameProblem : null}
          </p>
        </div>
      ) : null}
      <Button type="button" className={fullWidth ? "h-10 w-full" : "h-10 w-full sm:w-auto sm:min-w-44"} disabled={locked} onClick={start}>
        {working ? (
          <>
            <Loader2 className="size-4 animate-spin" aria-hidden />
            {phase === "confirming" ? "Confirming payment…" : "Opening checkout…"}
          </>
        ) : (
          label
        )}
      </Button>
      <div aria-live="polite">
        {phase === "slow" ? (
          <p className="text-sm text-muted-foreground">
            We have not heard back from the payment provider yet. This can take a minute. Check{" "}
            <Link href="/account" className="underline underline-offset-2">
              your account
            </Link>{" "}
            shortly; if you were charged, your plan will appear there.
          </p>
        ) : null}
        {offerGone ? <p className="text-sm text-muted-foreground">Early-bird offer unavailable, full price applies.</p> : null}
        {error ? (
          <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>
              {error.text}
              {error.link ? (
                <>
                  {" "}
                  <Link href="/account" className="underline underline-offset-2">
                    Open your account
                  </Link>
                </>
              ) : null}
            </span>
          </p>
        ) : null}
      </div>
    </div>
  );
}
