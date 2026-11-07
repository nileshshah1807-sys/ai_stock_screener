import { NextResponse } from "next/server";

import { isUnknownSubscription } from "@/lib/billing.mjs";
import { notifyCancelled } from "@/lib/customer-email-server";
import { createAdminClient } from "@/lib/supabase/admin";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const fail = (error: string, status: number) => NextResponse.json({ error }, { status });

/**
 * Cancels the signed-in user's subscription. A paid (active) one ends at the
 * end of the period already paid for; one still waiting for its first charge
 * (trial) is cancelled at once, there being nothing paid to run out. Access
 * follows the stored period end either way. 200: {status, current_period_end}.
 */
export async function POST() {
  const keyId = process.env.RAZORPAY_KEY_ID;
  const keySecret = process.env.RAZORPAY_KEY_SECRET;
  const admin = createAdminClient();
  if (!keyId || !keySecret || !admin) return fail("billing_not_configured", 503);

  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const userId = typeof data?.claims?.sub === "string" ? data.claims.sub : "";
  if (!userId) return fail("unauthenticated", 401);

  const { data: sub } = await admin
    .from("subscriptions")
    .select("status, razorpay_subscription_id, plan_id, current_period_end")
    .eq("user_id", userId)
    .maybeSingle();
  if (!sub?.razorpay_subscription_id || !sub.plan_id) return fail("no_subscription", 404);
  if (sub.status === "cancelled" || sub.status === "expired") return fail("already_cancelled", 409);

  const atCycleEnd = sub.status === "active";
  const response = await fetch(`https://api.razorpay.com/v1/subscriptions/${sub.razorpay_subscription_id}/cancel`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Basic ${Buffer.from(`${keyId}:${keySecret}`).toString("base64")}`,
    },
    body: JSON.stringify({ cancel_at_cycle_end: atCycleEnd ? 1 : 0 }),
  }).catch(() => null);
  if (response && !response.ok && isUnknownSubscription(response.status, await response.json().catch(() => null))) {
    console.warn(`cancel: Razorpay does not know ${sub.razorpay_subscription_id}; nothing to cancel.`);
    return fail("unknown_subscription", 404); // nothing at Razorpay to act on; the row is left for support
  }
  if (!response?.ok) return fail("razorpay_error", 502);

  // The webhook confirms it; the page should not wait for that.
  await admin
    .from("subscriptions")
    .update({ status: "cancelled", updated_at: new Date().toISOString() })
    .eq("user_id", userId);
  await notifyCancelled(admin, userId);
  return NextResponse.json({ status: "cancelled", current_period_end: sub.current_period_end });
}
