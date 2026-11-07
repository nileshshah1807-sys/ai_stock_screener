import { NextResponse } from "next/server";

import { isUnknownSubscription } from "@/lib/billing.mjs";
import { PAYMENT_LIMIT, paymentRows } from "@/lib/payments.mjs";
import { createAdminClient } from "@/lib/supabase/admin";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const RAZORPAY = "https://api.razorpay.com/v1";
const NO_STORE = { "Cache-Control": "private, no-store" };
const fail = (error: string, status: number) => NextResponse.json({ error }, { status, headers: NO_STORE });

type Invoice = { subscription_id?: string; payment_id?: string };

/**
 * The signed-in person's own payments, read from Razorpay for the one
 * subscription their row names. The user id comes from the verified token, never
 * from the request, and each invoice must name that same subscription before it is
 * kept. The keys stay here; the browser gets only the fields payments.mjs chooses.
 * 200: {payments: [...]} (empty when they have never subscribed).
 */
export async function GET() {
  const keyId = process.env.RAZORPAY_KEY_ID;
  const keySecret = process.env.RAZORPAY_KEY_SECRET;
  const admin = createAdminClient();
  if (!keyId || !keySecret || !admin) return fail("billing_not_configured", 503);

  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const userId = typeof data?.claims?.sub === "string" ? data.claims.sub : "";
  if (!userId) return fail("unauthenticated", 401);

  const { data: sub } = await admin.from("subscriptions").select("razorpay_subscription_id").eq("user_id", userId).maybeSingle();
  const subscriptionId = sub?.razorpay_subscription_id;
  if (!subscriptionId) return NextResponse.json({ payments: [] }, { headers: NO_STORE });

  const headers = { Authorization: `Basic ${Buffer.from(`${keyId}:${keySecret}`).toString("base64")}` };
  const get = (path: string) =>
    fetch(`${RAZORPAY}${path}`, { headers, cache: "no-store" }).then(
      (r) => (r.ok ? r.json() : null),
      () => null,
    );

  const listing = await fetch(`${RAZORPAY}/invoices?subscription_id=${encodeURIComponent(subscriptionId)}&count=${PAYMENT_LIMIT}`, { headers, cache: "no-store" }).catch(() => null);
  const list = listing ? await listing.json().catch(() => null) : null;
  // An id Razorpay does not know (another mode, or stale): no payments, not an error.
  if (listing && !listing.ok && isUnknownSubscription(listing.status, list)) return NextResponse.json({ payments: [] }, { headers: NO_STORE });
  if (!listing?.ok || !Array.isArray(list?.items)) return fail("razorpay_error", 502);
  const invoices: Invoice[] = list.items.filter((invoice: Invoice) => invoice.subscription_id === subscriptionId);

  const ids = [...new Set(invoices.map((invoice) => invoice.payment_id).filter((id): id is string => typeof id === "string"))];
  const payments = await Promise.all(ids.map((id) => get(`/payments/${encodeURIComponent(id)}`)));
  const byId: Record<string, unknown> = {};
  ids.forEach((id, index) => {
    if (payments[index]) byId[id] = payments[index];
  });

  return NextResponse.json({ payments: paymentRows(invoices, byId) }, { headers: NO_STORE });
}
