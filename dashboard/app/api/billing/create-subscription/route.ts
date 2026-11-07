import { NextResponse, type NextRequest } from "next/server";

import { buyerName, checkoutAction, customerBody, lookupResult, startSubscription } from "@/lib/billing.mjs";
import { previewCheckoutBlock, withTestIds } from "@/lib/plan-overrides.mjs";
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
  // Outside production only listed test accounts may check out: this deploy shares the live database.
  const blocked = previewCheckoutBlock(data?.claims?.email);
  if (blocked) return fail(blocked, 403);

  const email = typeof data?.claims?.email === "string" ? data.claims.email : "";
  const name = buyerName(data?.claims?.user_metadata?.full_name, email);
  const wanted = await request.json().then((b) => (typeof b?.plan_id === "string" ? b.plan_id : null)).catch(() => null);

  // The user's row (id from the verified token) and the plan with its Razorpay id.
  const { data: sub } = await admin
    .from("subscriptions")
    .select("status, plan_id, razorpay_subscription_id")
    .eq("user_id", userId)
    .maybeSingle();
  if (!sub) return fail("no_subscription", 404);
  if (checkoutAction(sub, null, "") === "refuse") return fail("already_subscribed", 409);

  let query = admin
    .from("plans")
    .select("id, name, amount_paise, period, razorpay_plan_id, razorpay_offer_id, offer_amount_paise")
    .eq("active", true)
    .not("razorpay_plan_id", "is", null);
  if (wanted) query = query.eq("id", wanted);
  const { data: plans } = await query.order("created_at").limit(1);
  const plan = plans?.[0] ? withTestIds(plans[0]) : null; // Preview: test-mode ids, see plan-overrides
  if (!plan) return fail("no_active_plan", 404);

  const auth = `Basic ${Buffer.from(`${keyId}:${keySecret}`).toString("base64")}`;

  // A subscription already started for this user is never duplicated: both would
  // charge. Ask Razorpay where it stands.
  let existing: { id?: string; status?: string; plan_id?: string; offer_id?: string | null; start_at?: number | null } | null = null;
  if (sub.razorpay_subscription_id) {
    const found = await fetch(`${RAZORPAY_SUBSCRIPTIONS}/${sub.razorpay_subscription_id}`, {
      headers: { Authorization: auth },
    }).catch(() => null);
    const looked = lookupResult(Boolean(found?.ok), found?.status ?? 0, await found?.json().catch(() => null));
    if ("error" in looked) return fail("razorpay_error", 502);
    if ("stale" in looked) console.warn(`create-subscription: Razorpay does not know ${sub.razorpay_subscription_id} (unknown); starting a new subscription for the user.`);
    else existing = looked.existing;
  }
  const action = checkoutAction(sub, existing, plan.razorpay_plan_id);
  if (action === "refuse") return fail("already_subscribed", 409);
  if (action === "reuse" && existing?.id) {
    const reused = Boolean(existing.offer_id);
    const { data: marked, error: markError } = await admin
      .from("subscriptions")
      .update({ offer_applied: reused })
      .eq("user_id", userId)
      .select("user_id");
    if (markError || !marked?.length) return fail("write_failed", 500);
    return NextResponse.json({
      subscription_id: existing.id,
      key_id: keyId,
      customer_name: name,
      plan: { id: plan.id, name: plan.name, amount_paise: plan.amount_paise, period: plan.period },
      offer_applied: reused,
      charged_amount_paise: existing.offer_id ? plan.offer_amount_paise : plan.amount_paise,
      trial_ends_at: existing.start_at ? new Date(existing.start_at * 1000).toISOString() : null,
    });
  }

  // The buyer as a Razorpay customer, so every invoice says who it is issued to. Never blocks the sale.
  let customerId: string | undefined;
  if (email) {
    const made = await fetch("https://api.razorpay.com/v1/customers", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: auth },
      body: JSON.stringify(customerBody({ name, email })),
      signal: AbortSignal.timeout(5000), // it sits in the buyer's wait and may fail anyway
    }).catch(() => null);
    const customer = made?.ok ? await made.json().catch(() => null) : null;
    if (typeof customer?.id === "string") customerId = customer.id;
    else console.warn(`create-subscription: Razorpay customer not created (status ${made?.status ?? "none"}); subscribing without one.`);
  }

  // The introductory offer, while it is open (the database decides).
  const { data: offerOpen } = plan.razorpay_offer_id
    ? await admin.rpc("plan_offer_open", { p_plan: plan.id })
    : { data: false };
  const { response, offered, rejection } = await startSubscription(
    async (body: unknown) => {
      const res = await fetch(RAZORPAY_SUBSCRIPTIONS, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: auth },
        body: JSON.stringify(body),
      }).catch(() => null);
      return { ok: Boolean(res?.ok), status: res?.status ?? 0, json: await res?.json().catch(() => null) };
    },
    { plan, userId, offerId: offerOpen ? plan.razorpay_offer_id : null, customerId },
  );
  // Where an admin looks: the deployment's logs. admin_actions needs an admin as actor, and this is a buyer's request.
  if (rejection) console.warn(`create-subscription: Razorpay rejected offer ${plan.razorpay_offer_id} on plan ${plan.id}; sold at full price. ${rejection}`);
  const created = response.ok ? response.json : null;
  if (!created?.id) return fail("razorpay_error", 502);

  // Remember which Razorpay subscription is this user's. plan_id is set by the
  // webhook when the mandate is authorised, so it marks a subscription that is
  // set up, not one that was only started.
  const { data: stored, error: storeError } = await admin
    .from("subscriptions")
    .update({
      razorpay_subscription_id: created.id,
      offer_applied: offered,
      plan_amount_paise: plan.amount_paise, // what they took: a later price change never rewrites it
      updated_at: new Date().toISOString(),
    })
    .eq("user_id", userId)
    .select("user_id");
  if (storeError || !stored?.length) return fail("write_failed", 500); // never charge a subscription we cannot match

  return NextResponse.json({
    subscription_id: created.id,
    key_id: keyId,
    customer_name: name,
    plan: { id: plan.id, name: plan.name, amount_paise: plan.amount_paise, period: plan.period },
    offer_applied: offered,
    offer_unavailable: Boolean(rejection),
    charged_amount_paise: offered ? plan.offer_amount_paise : plan.amount_paise,
    trial_ends_at: null,
  });
}
