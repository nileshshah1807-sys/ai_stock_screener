import { NextResponse, type NextRequest } from "next/server";

import { newSubscriptionBody } from "@/lib/billing.mjs";
import { createAdminClient } from "@/lib/supabase/admin";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const RAZORPAY_SUBSCRIPTIONS = "https://api.razorpay.com/v1/subscriptions";

const fail = (error: string, status: number) => NextResponse.json({ error }, { status });

/**
 * Starts a Razorpay subscription for the signed-in user and returns what
 * Razorpay Checkout needs. Open to any signed-in user, including one whose
 * trial has ended (that user is exactly who must pay), so it reads the token
 * directly instead of going through getViewer(). Payment is confirmed only by
 * the webhook, never by this call. Contract: see the billing PR.
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

  const wanted = await request.json().then((b) => (typeof b?.plan_id === "string" ? b.plan_id : null)).catch(() => null);

  // The viewer's own row (RLS), then the plan with its Razorpay id (service role).
  const { data: sub } = await supabase
    .from("subscriptions")
    .select("status, trial_ends_at")
    .eq("user_id", userId)
    .maybeSingle();
  if (sub?.status === "active") return fail("already_subscribed", 409);

  let query = admin
    .from("plans")
    .select("id, name, amount_paise, period, razorpay_plan_id")
    .eq("active", true)
    .not("razorpay_plan_id", "is", null);
  if (wanted) query = query.eq("id", wanted);
  const { data: plans } = await query.order("created_at").limit(1);
  const plan = plans?.[0];
  if (!plan) return fail("no_active_plan", 404);

  const body = newSubscriptionBody(
    { plan, userId, trialEndsAt: sub?.status === "trialing" ? sub.trial_ends_at : null },
    Date.now() / 1000,
  );
  const response = await fetch(RAZORPAY_SUBSCRIPTIONS, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Basic ${Buffer.from(`${keyId}:${keySecret}`).toString("base64")}`,
    },
    body: JSON.stringify(body),
  }).catch(() => null);
  const created = response?.ok ? await response.json().catch(() => null) : null;
  if (!created?.id) return fail("razorpay_error", 502);

  // Remember which Razorpay subscription is this user's; the webhook also
  // carries user_id in the subscription's notes.
  await admin
    .from("subscriptions")
    .upsert({ user_id: userId, plan_id: plan.id, razorpay_subscription_id: created.id, updated_at: new Date().toISOString() }, { onConflict: "user_id" });

  return NextResponse.json({
    subscription_id: created.id,
    key_id: keyId,
    plan: { id: plan.id, name: plan.name, amount_paise: plan.amount_paise, period: plan.period },
    trial_ends_at: body.start_at ? new Date(body.start_at * 1000).toISOString() : null,
  });
}
