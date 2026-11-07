/**
 * "Refund & end access": the decision and the order of steps, with every
 * outside call injected so the order is testable. Money first and alone: if the
 * refund fails nothing else changes. Once it has gone through, access must end
 * whatever else fails, and the admin is told exactly what was done.
 */

const REFUNDABLE = ["captured", "partially_refunded", "refunded"];

/**
 * The newest payment that was taken (Razorpay payment objects), with what is
 * still refundable. Null when the subscription never captured one.
 * @returns {{id: string, paise: number, currency: string, at: number, refundablePaise: number}|null}
 */
export function pickPayment(payments) {
  const taken = (Array.isArray(payments) ? payments : [])
    .filter((p) => p && typeof p.id === "string" && REFUNDABLE.includes(p.status) && Number.isFinite(p.amount) && Number.isFinite(p.created_at))
    .sort((a, b) => b.created_at - a.created_at);
  const p = taken[0];
  if (!p) return null;
  const refunded = Number.isFinite(p.amount_refunded) ? p.amount_refunded : 0;
  return {
    id: p.id,
    paise: p.amount,
    currency: typeof p.currency === "string" ? p.currency : "INR",
    at: p.created_at,
    refundablePaise: p.status === "refunded" ? 0 : Math.max(0, p.amount - refunded),
  };
}

/** Who may be refunded: not yourself, not an admin, and only someone with a Razorpay subscription. */
export function refundGuard({ actorId, target, sub }) {
  if (!target) return { ok: false, message: "User not found." };
  if (target.id === actorId) return { ok: false, message: "You cannot refund yourself." };
  if (target.role === "admin") return { ok: false, message: "Admins are not refunded here." };
  if (!sub?.razorpay_subscription_id) return { ok: false, message: "This user has no Razorpay subscription." };
  return { ok: true, subscriptionId: sub.razorpay_subscription_id };
}

/**
 * deps: payment() -> pickPayment result; refund(id, paise) -> {ok, id?, error?}; holdCancelMail(); notifyRefund(paymentId, paise);
 * cancel() -> "cancelled" | "already" | "failed"; endAccess() -> boolean.
 * Returns {ok, done: string[], problems: string[], payment}. ok means all four
 * outcomes hold (refund, cancel, access ended); done lists what changed.
 */
export async function refundAndEnd(deps, expectedPaymentId) {
  const payment = await deps.payment();
  if (!payment) return { ok: false, done: [], problems: ["No captured payment was found for this subscription (or Razorpay could not be read). Nothing was changed."], payment: null };
  if (payment.id !== expectedPaymentId) {
    return { ok: false, done: [], problems: ["The latest payment is not the one you confirmed. Reopen the dialog. Nothing was changed."], payment };
  }

  const done = [];
  const problems = [];
  if (payment.refundablePaise > 0) {
    const refund = await deps.refund(payment.id, payment.refundablePaise);
    if (!refund.ok) {
      return { ok: false, done, problems: [`Razorpay refused the refund${refund.error ? ` (${refund.error})` : ""}. Nothing was changed.`], payment };
    }
    done.push(`refunded ${payment.id}`);
  } else {
    done.push(`${payment.id} was already refunded (no second refund)`);
  }

  // The refund email says access ended: claim the generic "cancelled" mail first so the webhook does not also send it.
  await deps.holdCancelMail();
  const cancelled = await deps.cancel();
  if (cancelled === "cancelled") done.push("cancelled the Razorpay subscription");
  else if (cancelled === "already") done.push("the Razorpay subscription was already cancelled");
  else problems.push("the Razorpay subscription could NOT be cancelled: cancel it in Razorpay, or it may charge again");

  if (await deps.endAccess()) done.push("ended access");
  else problems.push("access was NOT ended in Cupel: apply storage/billing_schema.sql if it is not applied, then run this again (the refund is not repeated)");

  // The email says access has ended, so only a fully done job sends it; a re-run after a partial failure sends it.
  // Keyed by the payment: one refund email per payment, however many clicks.
  if (problems.length === 0) await deps.notifyRefund(payment.id, payment.paise);
  return { ok: problems.length === 0, done, problems, payment };
}
