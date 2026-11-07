/**
 * The decision behind POST /api/billing/confirm, with its I/O injected so the
 * ownership checks are testable: returns { status, body } for the route to send.
 * Server only (node:crypto, via the signature check).
 */

import { subscriptionChange } from "./billing.mjs";
import { verifyPaymentSignature } from "./webhook-signature.mjs";

export async function confirmPayment({ userId, proof, keySecret, now, storedSubscriptionId, fetchEntity, apply }) {
  if (!userId) return { status: 401, body: { error: "unauthenticated" } };
  const paymentId = typeof proof?.razorpay_payment_id === "string" ? proof.razorpay_payment_id : "";
  const subscriptionId = typeof proof?.razorpay_subscription_id === "string" ? proof.razorpay_subscription_id : "";
  const signature = typeof proof?.razorpay_signature === "string" ? proof.razorpay_signature : "";
  if (!verifyPaymentSignature(paymentId, subscriptionId, signature, keySecret)) {
    return { status: 400, body: { error: "bad_signature" } };
  }
  if ((await storedSubscriptionId()) !== subscriptionId) {
    return { status: 403, body: { error: "not_your_subscription" } };
  }

  const before = Math.floor(now() / 1000); // taken before the fetch, so a later cancel is never older than this
  const entity = await fetchEntity(subscriptionId);
  if (entity?.stale) return { status: 200, body: { ok: true, applied: false, stale: true } }; // Razorpay does not know it: nothing to apply
  if (!entity?.id) return { status: 502, body: { error: "razorpay_error" } };

  const change = subscriptionChange(
    {
      event: `subscription.${entity.status}`,
      payload: { subscription: { entity } },
      // Razorpay's own clock, not ours: any later real event then wins in billing_apply_event.
      created_at: Number.isFinite(entity.current_start) ? entity.current_start : before,
    },
    `confirm:${paymentId}`,
  );
  // Not authorised or paid yet (status "created"), or not this user's: nothing to apply.
  if (!change || change.userId !== userId) return { status: 200, body: { ok: true, applied: false } };

  if (!(await apply(change))) return { status: 500, body: { error: "write_failed" } };
  return { status: 200, body: { ok: true, applied: true } };
}
