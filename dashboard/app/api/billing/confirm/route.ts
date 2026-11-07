import { NextResponse, type NextRequest } from "next/server";

import { subscriptionChange } from "@/lib/billing.mjs";
import { verifyPaymentSignature } from "@/lib/webhook-signature.mjs";
import { createAdminClient } from "@/lib/supabase/admin";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const fail = (error: string, status: number) => NextResponse.json({ error }, { status });

/**
 * Called by the checkout page the moment Razorpay's success handler fires, so a
 * paying user has access in seconds instead of when the webhook arrives. The
 * browser is not trusted: the payment signature (HMAC of payment id and
 * subscription id under RAZORPAY_KEY_SECRET) must verify, the subscription must
 * be the one stored for the signed-in user, and its state is read from Razorpay
 * itself, then written through billing_apply_event, the webhook's own path.
 * The webhook later changes nothing it has not already changed.
 */
export async function POST(request: NextRequest) {
  const keyId = process.env.RAZORPAY_KEY_ID;
  const keySecret = process.env.RAZORPAY_KEY_SECRET;
  const admin = createAdminClient();
  if (!keyId || !keySecret || !admin) return fail("billing_not_configured", 503);

  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const userId = typeof data?.claims?.sub === "string" ? data.claims.sub : "";
  if (!userId) return fail("unauthenticated", 401);

  const body = await request.json().catch(() => null);
  const paymentId = typeof body?.razorpay_payment_id === "string" ? body.razorpay_payment_id : "";
  const subscriptionId = typeof body?.razorpay_subscription_id === "string" ? body.razorpay_subscription_id : "";
  const signature = typeof body?.razorpay_signature === "string" ? body.razorpay_signature : "";
  if (!verifyPaymentSignature(paymentId, subscriptionId, signature, keySecret)) return fail("bad_signature", 400);

  const { data: row } = await admin
    .from("subscriptions")
    .select("razorpay_subscription_id")
    .eq("user_id", userId)
    .maybeSingle();
  if (!row || row.razorpay_subscription_id !== subscriptionId) return fail("not_your_subscription", 403);

  const found = await fetch(`https://api.razorpay.com/v1/subscriptions/${subscriptionId}`, {
    headers: { Authorization: `Basic ${Buffer.from(`${keyId}:${keySecret}`).toString("base64")}` },
  }).catch(() => null);
  const entity = found?.ok ? await found.json().catch(() => null) : null;
  if (!entity?.id) return fail("razorpay_error", 502);

  const change = subscriptionChange(
    {
      event: `subscription.${entity.status}`,
      payload: { subscription: { entity } },
      created_at: Math.floor(Date.now() / 1000),
    },
    `confirm:${paymentId}`,
  );
  // Not authorised or paid yet (status "created"): nothing to apply; the webhook will.
  if (!change || change.userId !== userId) return NextResponse.json({ ok: true, applied: false });

  const { error } = await admin.rpc("billing_apply_event", {
    p_razorpay_subscription_id: change.razorpaySubscriptionId,
    p_user_id: change.userId,
    p_plan_id: change.planId,
    p_status: change.status,
    p_current_period_end: change.currentPeriodEnd,
    p_event_id: change.eventId,
    p_event_at: change.eventAt,
  });
  if (error) return fail("write_failed", 500);
  return NextResponse.json({ ok: true, applied: true });
}
