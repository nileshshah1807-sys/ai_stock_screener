/**
 * The pure rules of self-serve billing: who has access, whether a Razorpay
 * webhook is genuine, and what a subscription event changes.
 *
 * Plain .mjs so `node --test` covers it without a build step. The access rule
 * is kept equal to dashboard_has_access() in storage/billing_schema.sql by
 * its test; the price is never here (it is plans.amount_paise).
 */

import { createHmac, timingSafeEqual } from "node:crypto";

/** Plans that never expire: invited users and admins. */
const PERMANENT_PLANS = ["admin", "allowlist"];

/**
 * Whether a token's claims grant access, read the way the database reads them.
 * `plan` is absent on a token issued before the hook was enabled; that case is
 * the caller's (it falls back to the invite list).
 */
export function hasAccess(claims, nowSeconds) {
  const plan = claims?.plan;
  if (typeof plan !== "string") return false;
  if (PERMANENT_PLANS.includes(plan)) return true;
  if (plan === "none") return false;
  const until = claims.access_until;
  return Number.isInteger(until) && until > Math.floor(nowSeconds);
}

/** The Razorpay webhook signature: hex HMAC-SHA256 of the raw body. */
export function verifySignature(rawBody, signature, secret) {
  if (!secret || typeof signature !== "string" || !signature) return false;
  const expected = createHmac("sha256", secret).update(rawBody).digest("hex");
  const given = Buffer.from(signature, "utf8");
  const wanted = Buffer.from(expected, "utf8");
  return given.length === wanted.length && timingSafeEqual(given, wanted);
}

/** Razorpay subscription status -> ours; a missing one leaves the stored status alone. */
const STATUS = {
  active: "active",
  pending: "past_due",
  halted: "past_due",
  paused: "past_due",
  cancelled: "cancelled",
  completed: "expired",
  expired: "expired",
};

/**
 * What a webhook event changes, or null when it changes nothing we store
 * (not a subscription event, or a stage before payment: created, authenticated).
 * `eventId` is Razorpay's X-Razorpay-Event-Id header.
 */
export function subscriptionChange(event, eventId) {
  const entity = event?.payload?.subscription?.entity;
  if (!String(event?.event ?? "").startsWith("subscription.") || !entity?.id) return null;
  const status = STATUS[entity.status];
  if (!status) return null;
  const end = Number.isFinite(entity.current_end) ? new Date(entity.current_end * 1000).toISOString() : null;
  return {
    razorpaySubscriptionId: String(entity.id),
    userId: entity.notes?.user_id ? String(entity.notes.user_id) : null,
    planId: entity.notes?.plan_id ? String(entity.notes.plan_id) : null,
    status,
    currentPeriodEnd: end,
    eventId: String(eventId ?? ""),
    eventAt: Number.isFinite(event.created_at) ? new Date(event.created_at * 1000).toISOString() : null,
  };
}

/**
 * Whether an event is new to the stored subscription: not the one already
 * applied, and not older than it (Razorpay may deliver out of order or retry).
 */
export function isNewEvent(stored, change) {
  if (!change.eventId || !change.eventAt) return false;
  if (stored?.last_event_id === change.eventId) return false;
  return !stored?.last_event_at || Date.parse(change.eventAt) >= Date.parse(stored.last_event_at);
}

/** Subscriptions are charged until cancelled; Razorpay needs a finite count. */
const TOTAL_COUNT = { monthly: 120, yearly: 10 };
/** A first charge less than this far ahead is simply charged now. */
const MIN_TRIAL_LEAD_SECONDS = 60 * 60;

/**
 * The body for Razorpay's create-subscription call. With trial time left the
 * first charge waits for it (the mandate is authorised now); else it is now.
 */
export function newSubscriptionBody({ plan, userId, trialEndsAt }, nowSeconds) {
  /** @type {{plan_id: string, total_count: number, customer_notify: number, notes: {user_id: string, plan_id: string}, start_at?: number}} */
  const body = {
    plan_id: plan.razorpay_plan_id,
    total_count: TOTAL_COUNT[plan.period],
    customer_notify: 1,
    notes: { user_id: userId, plan_id: plan.id },
  };
  const trialEnd = trialEndsAt ? Math.floor(Date.parse(trialEndsAt) / 1000) : 0;
  if (trialEnd - nowSeconds > MIN_TRIAL_LEAD_SECONDS) body.start_at = trialEnd;
  return body;
}

/**
 * The viewer a token's claims describe, or null. Admin keeps the admin role;
 * everyone else (invited, trial, paid) is a viewer.
 */
export function viewerFromClaims(claims, nowSeconds) {
  if (!hasAccess(claims, nowSeconds)) return null;
  return {
    role: claims.plan === "admin" ? "admin" : "viewer",
    plan: String(claims.plan),
    accessUntil: Number.isInteger(claims.access_until) ? claims.access_until : null,
  };
}
