import "server-only";

import { pickPayment, refundAndEnd } from "@/lib/admin-refund.mjs";
import { isUnknownSubscription } from "@/lib/billing.mjs";
import { claimCancelledEmail, sendRefundEmail } from "@/lib/customer-email-server";
import type { adminContext } from "@/lib/admin";

type Ctx = NonNullable<Awaited<ReturnType<typeof adminContext>>>;

const RAZORPAY = "https://api.razorpay.com/v1";
const auth = () => {
  const id = process.env.RAZORPAY_KEY_ID;
  const secret = process.env.RAZORPAY_KEY_SECRET;
  return id && secret ? `Basic ${Buffer.from(`${id}:${secret}`).toString("base64")}` : null;
};

async function call(path: string, init: RequestInit = {}) {
  const authorization = auth();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Razorpay's reply is read field by field
  if (!authorization) return { ok: false, status: 0, json: null as any };
  const res = await fetch(`${RAZORPAY}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: authorization },
    cache: "no-store",
  }).catch(() => null);
  return { ok: Boolean(res?.ok), status: res?.status ?? 0, json: res ? await res.json().catch(() => null) : null };
}

/** Razorpay does not know the stored subscription id (another mode, or stale): nothing to refund. */
export const UNKNOWN = Symbol("unknown subscription");

/** The subscription's payments, read as /api/billing/payments does: its invoices, then each payment. */
async function paymentsOf(subscriptionId: string) {
  const list = await call(`/invoices?subscription_id=${encodeURIComponent(subscriptionId)}&count=24`);
  if (isUnknownSubscription(list.status, list.json)) return UNKNOWN;
  if (!list.ok || !Array.isArray(list.json?.items)) return null;
  const ids = [...new Set<string>(list.json.items
    .filter((i: { subscription_id?: string }) => i.subscription_id === subscriptionId)
    .map((i: { payment_id?: string }) => i.payment_id)
    .filter((id: unknown): id is string => typeof id === "string"))];
  const fetched = await Promise.all(ids.map((id) => call(`/payments/${encodeURIComponent(id)}`)));
  if (fetched.some((r) => !r.ok)) return null;
  return fetched.map((r) => r.json);
}

/** The payment a refund would hit, for the confirm step. Null = Razorpay not readable or no payment. */
export async function refundCandidate(subscriptionId: string) {
  const payments = await paymentsOf(subscriptionId);
  if (payments === UNKNOWN) return UNKNOWN;
  return payments ? pickPayment(payments) : null;
}

/** Refund, cancel, end access, in that order (see lib/admin-refund.mjs). */
export function runRefund(ctx: Ctx, userId: string, subscriptionId: string, paymentId: string) {
  return refundAndEnd(
    {
      payment: async () => {
        const found = await refundCandidate(subscriptionId);
        return found === UNKNOWN ? null : found;
      },
      refund: async (id: string, paise: number) => {
        const r = await call(`/payments/${encodeURIComponent(id)}/refund`, { method: "POST", body: JSON.stringify({ amount: paise, speed: "normal", notes: { reason: "admin refund and end access" } }) });
        return { ok: r.ok, id: r.json?.id as string | undefined, error: r.json?.error?.description as string | undefined };
      },
      holdCancelMail: () => claimCancelledEmail(ctx.db, userId, subscriptionId),
      notifyRefund: async (key: string, paise: number) => void (await sendRefundEmail(ctx.db, userId, key, paise)),
      cancel: async () => {
        const state = await call(`/subscriptions/${encodeURIComponent(subscriptionId)}`);
        if ((state.ok && state.json?.status === "cancelled") || isUnknownSubscription(state.status, state.json)) return "already" as const;
        const r = await call(`/subscriptions/${encodeURIComponent(subscriptionId)}/cancel`, { method: "POST", body: JSON.stringify({ cancel_at_cycle_end: 0 }) });
        return r.ok ? ("cancelled" as const) : ("failed" as const);
      },
      endAccess: async () => {
        const { data, error } = await ctx.db.rpc("billing_refund_end_access", { p_user_id: userId, p_razorpay_subscription_id: subscriptionId });
        return !error && data === true;
      },
    },
    paymentId,
  );
}
