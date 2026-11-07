import "server-only";

import type { SupabaseClient } from "@supabase/supabase-js";

import { compose, resendSend, sendOnce } from "@/lib/customer-email.mjs";

/**
 * Sends Cupel's emails to customers (billing events, trial ending, refunds).
 * Server only, through Resend, keyed by RESEND_API_KEY: without it every call
 * logs and does nothing. A send is recorded first in customer_emails
 * (user, kind, key), so the webhook, /confirm and /cancel racing for one event
 * send one email. Nothing here throws: a billing request never fails over email.
 */

type Kind = "paid" | "cancelled" | "trial_ending" | "refund";
type Row = { user_id: string; plan_id: string | null; razorpay_subscription_id: string | null; current_period_end: string | null; trial_ends_at: string | null };

const COLUMNS = "user_id, plan_id, razorpay_subscription_id, current_period_end, trial_ends_at";

async function deliver(admin: SupabaseClient, userId: string, kind: Kind, key: string, data: Record<string, unknown>) {
  const apiKey = process.env.RESEND_API_KEY;
  return sendOnce({
    apiKey,
    claim: async () => {
      const { data: rows, error } = await admin.from("customer_emails").upsert({ user_id: userId, kind, event_key: key }, { onConflict: "user_id,kind,event_key", ignoreDuplicates: true }).select("user_id");
      if (error) throw error;
      return (rows?.length ?? 0) > 0;
    },
    release: async () => void (await admin.from("customer_emails").delete().eq("user_id", userId).eq("kind", kind).eq("event_key", key)),
    send: async () => {
      const { data: user } = await admin.auth.admin.getUserById(userId);
      const to = user?.user?.email;
      if (!to) throw new Error("no email address for the user");
      await resendSend(fetch, apiKey as string, { to, ...compose(kind, data) }, `${userId}/${kind}/${key}`);
    },
  });
}

async function period(admin: SupabaseClient, planId: string | null) {
  if (!planId) return undefined;
  const { data } = await admin.from("plans").select("period").eq("id", planId).maybeSingle();
  return data?.period as string | undefined;
}

/** After billing_apply_event changed a row: the first activation of a subscription is "paid", a cancellation is "cancelled". */
export async function notifyStatusChange(admin: SupabaseClient, razorpaySubscriptionId: string, status: string | null) {
  const kind: Kind | null = status === "active" ? "paid" : status === "cancelled" ? "cancelled" : null;
  if (!kind) return;
  try {
    const { data: row } = await admin.from("subscriptions").select(COLUMNS).eq("razorpay_subscription_id", razorpaySubscriptionId).maybeSingle<Row>();
    if (!row) return;
    await deliver(admin, row.user_id, kind, razorpaySubscriptionId, kind === "paid" ? { period: await period(admin, row.plan_id) } : { endsAt: accessEnd(row) });
  } catch (error) {
    console.warn("customer email not sent", error);
  }
}

/** The later of the paid period's end and the trial's end: what the access token also uses. */
function accessEnd(row: Row) {
  return [row.current_period_end, row.trial_ends_at].filter(Boolean).sort().pop();
}

/** The user just cancelled (/api/billing/cancel). The webhook's later cancelled event finds the same key and sends nothing. */
export async function notifyCancelled(admin: SupabaseClient, userId: string) {
  try {
    const { data: row } = await admin.from("subscriptions").select(COLUMNS).eq("user_id", userId).maybeSingle<Row>();
    if (!row?.razorpay_subscription_id) return;
    await deliver(admin, userId, "cancelled", row.razorpay_subscription_id, { endsAt: accessEnd(row) });
  } catch (error) {
    console.warn("customer email not sent", error);
  }
}

/** The daily job: a trial that ends within two days gets one email (the key is its end time). `members`: lowercase emails of admins and the allowlist, who get none. */
export async function notifyTrialEnding(admin: SupabaseClient, userId: string, trialEndsAt: string, members: Set<string>) {
  const { data: user } = await admin.auth.admin.getUserById(userId).catch(() => ({ data: null }));
  if (members.has(String(user?.user?.email ?? "").toLowerCase())) return "skipped" as const;
  return deliver(admin, userId, "trial_ending", trialEndsAt, { endsAt: trialEndsAt }).catch(() => "failed" as const);
}

/**
 * A refund was processed. `refundKey` is anything unique to that refund (the
 * Razorpay refund or payment id), so a repeat call sends nothing. For the
 * admin "Refund & end access" action: call it once the refund has gone through.
 */
export async function sendRefundEmail(admin: SupabaseClient, userId: string, refundKey: string, amountPaise?: number) {
  return deliver(admin, userId, "refund", refundKey, { amountPaise }).catch(() => "failed" as const);
}

/** Marks the "cancelled" email for this subscription as sent, without sending it: an admin refund sends its own email, and the webhook's cancelled event must not add "subscribe again". Never throws. */
export async function claimCancelledEmail(admin: SupabaseClient, userId: string, razorpaySubscriptionId: string) {
  try {
    await admin.from("customer_emails").upsert({ user_id: userId, kind: "cancelled", event_key: razorpaySubscriptionId }, { onConflict: "user_id,kind,event_key", ignoreDuplicates: true });
  } catch (error) {
    console.warn("cancelled email not held", error);
  }
}
