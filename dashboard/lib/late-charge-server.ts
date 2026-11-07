import "server-only";

import type { SupabaseClient } from "@supabase/supabase-js";

const RAZORPAY = "https://api.razorpay.com/v1";
const auth = () => {
  const id = process.env.RAZORPAY_KEY_ID;
  const secret = process.env.RAZORPAY_KEY_SECRET;
  return id && secret ? `Basic ${Buffer.from(`${id}:${secret}`).toString("base64")}` : null;
};
const post = async (path: string, body: unknown) => {
  const authorization = auth();
  if (!authorization) return false;
  const res = await fetch(`${RAZORPAY}${path}`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: authorization }, body: JSON.stringify(body), signal: AbortSignal.timeout(10000) }).catch(() => null);
  return Boolean(res?.ok);
};

/** Stop the subscription now (not at cycle end). */
export const cancelNow = (subscriptionId: string) => post(`/subscriptions/${encodeURIComponent(subscriptionId)}/cancel`, { cancel_at_cycle_end: 0 });
/** Refund the whole payment (no amount = in full). A payment already fully refunded (a redelivery after a lost reply) counts as done. */
export async function refundPayment(paymentId: string) {
  const authorization = auth();
  if (!authorization) return false;
  const read = await fetch(`${RAZORPAY}/payments/${encodeURIComponent(paymentId)}`, { headers: { Authorization: authorization }, signal: AbortSignal.timeout(10000), cache: "no-store" }).catch(() => null);
  const payment = read?.ok ? await read.json().catch(() => null) : null;
  if (payment && (payment.status === "refunded" || (Number.isFinite(payment.amount) && payment.amount_refunded >= payment.amount))) return true;
  return post(`/payments/${encodeURIComponent(paymentId)}/refund`, { speed: "normal", notes: { reason: "charge after cancellation" } });
}

/** The alert: a warning in the logs and an admin_actions row (system actor) the admin page can show. */
export async function alertLateCharge(admin: SupabaseClient, userId: string | null, detail: Record<string, unknown>) {
  console.warn("billing webhook: charge after cancellation", detail);
  const { error } = await admin.from("admin_actions").insert({
    admin_id: "00000000-0000-0000-0000-000000000000",
    admin_email: "system:billing-webhook",
    action: "late_charge_undone",
    target_id: userId,
    detail,
  });
  if (error) console.warn("late charge alert not recorded", error.message);
}
