import { NextResponse, type NextRequest } from "next/server";

import { lateCharge, subscriptionChange, undoLateCharge } from "@/lib/billing.mjs";
import { notifyStatusChange } from "@/lib/customer-email-server";
import { alertLateCharge, cancelNow, refundPayment } from "@/lib/late-charge-server";
import { verifySignature } from "@/lib/webhook-signature.mjs";
import { createAdminClient } from "@/lib/supabase/admin";

export const dynamic = "force-dynamic";

/**
 * Razorpay's webhook. Anyone can POST here, so nothing is read from the body
 * until its X-Razorpay-Signature (HMAC-SHA256 of the raw body, keyed by
 * RAZORPAY_WEBHOOK_SECRET) checks out. Each event is applied once and in
 * order by billing_apply_event (SQL): a repeat or an older one is acknowledged
 * and ignored, because Razorpay retries and may reorder.
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
  // A charge for a subscription we hold as cancelled, after its paid period: undo it (cancel, refund, alert)
  // and do NOT apply it, which would give the person access back.
  if (event?.event === "subscription.charged") {
    const id = event?.payload?.subscription?.entity?.id;
    const { data: row } = typeof id === "string"
      ? await admin.from("subscriptions").select("user_id, status, current_period_end").eq("razorpay_subscription_id", id).maybeSingle()
      : { data: null };
    const late = lateCharge(event, row, Date.now());
    if (late.act) {
      const done = await undoLateCharge({ cancel: cancelNow, refund: refundPayment, alert: (detail: Record<string, unknown>) => alertLateCharge(admin, row?.user_id ?? null, detail) }, late);
      // A failed refund is retried by Razorpay's redelivery; the cancel and the alert are repeatable.
      return NextResponse.json(done.refunded ? { ok: true, undone: true } : { error: "refund_failed" }, { status: done.refunded ? 200 : 500 });
    }
  }
  const change = subscriptionChange(event, request.headers.get("x-razorpay-event-id"));
  if (!change) return NextResponse.json({ ok: true, ignored: true });

  // One statement decides and writes (billing_apply_event): a duplicate, a stale
  // event, or a subscription that is not ours changes no row. Razorpay retries
  // on 500.
  const { data: applied, error } = await admin.rpc("billing_apply_event", {
    p_razorpay_subscription_id: change.razorpaySubscriptionId,
    p_user_id: change.userId,
    p_plan_id: change.planId,
    p_status: change.status,
    p_current_period_end: change.currentPeriodEnd,
    p_event_id: change.eventId,
    p_event_at: change.eventAt,
  });
  if (error) return NextResponse.json({ error: "write_failed" }, { status: 500 });
  // A paying user whose subscription id we do not hold (e.g. a double-clicked checkout) would otherwise vanish silently.
  if (!applied && change.userId && change.status === "active") {
    console.warn("billing webhook: active event matched no row", change.razorpaySubscriptionId, change.userId);
  }
  // The write is done; the email must never fail it. At most once per subscription and kind.
  if (applied) await notifyStatusChange(admin, change.razorpaySubscriptionId, change.status);
  return NextResponse.json({ ok: true });
}
