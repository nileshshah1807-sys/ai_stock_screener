import { NextResponse, type NextRequest } from "next/server";

import { notifyStatusChange } from "@/lib/customer-email-server";
import { confirmPayment } from "@/lib/billing-confirm.mjs";
import { createAdminClient } from "@/lib/supabase/admin";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

/**
 * Called by the checkout page the moment Razorpay's success handler fires, so a
 * paying user has access in seconds instead of when the webhook arrives. The
 * browser is not trusted: the payment signature (HMAC of payment id and
 * subscription id under RAZORPAY_KEY_SECRET) must verify, the subscription must
 * be the one stored for the signed-in user, and its state is read from Razorpay
 * itself, then written through billing_apply_event, the webhook's own path.
 * The decisions live in lib/billing-confirm.mjs (tested); this is the I/O.
 */
export async function POST(request: NextRequest) {
  const keyId = process.env.RAZORPAY_KEY_ID;
  const keySecret = process.env.RAZORPAY_KEY_SECRET;
  const admin = createAdminClient();
  if (!keyId || !keySecret || !admin) return NextResponse.json({ error: "billing_not_configured" }, { status: 503 });

  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const userId = typeof data?.claims?.sub === "string" ? data.claims.sub : "";

  const { status, body } = await confirmPayment({
    userId,
    proof: await request.json().catch(() => null),
    keySecret,
    now: Date.now,
    storedSubscriptionId: async () => {
      const { data: row } = await admin.from("subscriptions").select("razorpay_subscription_id").eq("user_id", userId).maybeSingle();
      return row?.razorpay_subscription_id ?? null;
    },
    fetchEntity: async (id: string) => {
      const found = await fetch(`https://api.razorpay.com/v1/subscriptions/${id}`, {
        headers: { Authorization: `Basic ${Buffer.from(`${keyId}:${keySecret}`).toString("base64")}` },
      }).catch(() => null);
      return found?.ok ? await found.json().catch(() => null) : null;
    },
    apply: async (change: {
      razorpaySubscriptionId: string;
      userId: string | null;
      planId: string | null;
      status: string | null;
      currentPeriodEnd: string | null;
      eventId: string;
      eventAt: string | null;
    }) => {
      const { data: applied, error } = await admin.rpc("billing_apply_event", {
        p_razorpay_subscription_id: change.razorpaySubscriptionId,
        p_user_id: change.userId,
        p_plan_id: change.planId,
        p_status: change.status,
        p_current_period_end: change.currentPeriodEnd,
        p_event_id: change.eventId,
        p_event_at: change.eventAt,
      });
      // Only a write that changed the row: confirm may have lost to a newer event.
      if (!error && applied === true) await notifyStatusChange(admin, change.razorpaySubscriptionId, change.status);
      return !error;
    },
  });
  return NextResponse.json(body, { status });
}
