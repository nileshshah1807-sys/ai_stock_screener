import { NextResponse, type NextRequest } from "next/server";

import { isNewEvent, subscriptionChange, verifySignature } from "@/lib/billing.mjs";
import { createAdminClient } from "@/lib/supabase/admin";

export const dynamic = "force-dynamic";

/**
 * Razorpay's webhook. Anyone can POST here, so nothing is read from the body
 * until its X-Razorpay-Signature (HMAC-SHA256 of the raw body, keyed by
 * RAZORPAY_WEBHOOK_SECRET) checks out. Each event is applied once and in
 * order: an event id already applied, or older than the last one, is
 * acknowledged and ignored, because Razorpay retries and may reorder.
 * Register this URL for the subscription.* events.
 */
export async function POST(request: NextRequest) {
  const secret = process.env.RAZORPAY_WEBHOOK_SECRET;
  const admin = createAdminClient();
  if (!secret || !admin) return NextResponse.json({ error: "billing_not_configured" }, { status: 503 });

  const raw = await request.text();
  if (!verifySignature(raw, request.headers.get("x-razorpay-signature") ?? "", secret)) {
    return NextResponse.json({ error: "bad_signature" }, { status: 400 });
  }

  let event;
  try {
    event = JSON.parse(raw);
  } catch {
    return NextResponse.json({ error: "bad_body" }, { status: 400 });
  }
  const change = subscriptionChange(event, request.headers.get("x-razorpay-event-id"));
  if (!change) return NextResponse.json({ ok: true, ignored: true });

  // The row: by the Razorpay subscription id, else by the user id in the notes.
  let query = admin.from("subscriptions").select("user_id, last_event_id, last_event_at");
  query = change.userId
    ? query.or(`razorpay_subscription_id.eq.${change.razorpaySubscriptionId},user_id.eq.${change.userId}`)
    : query.eq("razorpay_subscription_id", change.razorpaySubscriptionId);
  const { data: rows, error: readError } = await query.limit(1);
  if (readError) return NextResponse.json({ error: "read_failed" }, { status: 500 }); // Razorpay retries
  const stored = rows?.[0];
  if (!stored) return NextResponse.json({ ok: true, ignored: true }); // not a user of ours
  if (!isNewEvent(stored, change)) return NextResponse.json({ ok: true, duplicate: true });

  const update: Record<string, unknown> = {
    razorpay_subscription_id: change.razorpaySubscriptionId,
    status: change.status,
    last_event_id: change.eventId,
    last_event_at: change.eventAt,
    updated_at: new Date().toISOString(),
  };
  if (change.currentPeriodEnd) update.current_period_end = change.currentPeriodEnd;
  if (change.planId) update.plan_id = change.planId;
  const { error } = await admin.from("subscriptions").update(update).eq("user_id", stored.user_id);
  if (error) return NextResponse.json({ error: "write_failed" }, { status: 500 });
  return NextResponse.json({ ok: true });
}
