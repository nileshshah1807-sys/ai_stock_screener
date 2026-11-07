import "server-only";

import {
  razorpayMode,
  razorpayPlanBody,
  revenueByPlan,
  swapPlan,
  validateOffer,
  validatePriceChange,
  validateTrialDays,
} from "@/lib/admin-plans.mjs";
import { adminContext, logAdminAction } from "@/lib/admin";

/** Server-only plan management. Every export re-checks the admin from the token. */

const RAZORPAY = "https://api.razorpay.com/v1";

export type AdminPlan = {
  id: string;
  name: string;
  period: "monthly" | "yearly";
  amount_paise: number;
  active: boolean;
  razorpay_plan_id: string | null;
  razorpay_offer_id: string | null;
  offer_name: string | null;
  offer_amount_paise: number | null;
  offer_ends_at: string | null;
  offer_limit: number | null;
};
export type PlansAdminData = {
  plans: AdminPlan[];
  revenue: { planId: string; subscribers: number; monthlyPaise: number }[];
  trialDays: number;
  mode: "live" | "test" | "unknown";
};
export type Result = { ok: true; message: string } | { ok: false; error: string };

const fail = (error: string): Result => ({ ok: false, error });

/** The admin (re-checked from the verified token on every call) and the Razorpay auth header; null = not an admin. */
async function context() {
  const ctx = await adminContext();
  if (!ctx) return null;
  const keyId = process.env.RAZORPAY_KEY_ID;
  const keySecret = process.env.RAZORPAY_KEY_SECRET;
  return { ctx, db: ctx.db, auth: keyId && keySecret ? `Basic ${Buffer.from(`${keyId}:${keySecret}`).toString("base64")}` : null };
}

const NOT_ADMIN = fail("Not allowed.");

export async function loadPlansAdmin(): Promise<PlansAdminData | null> {
  const c = await context();
  if (!c) return null;
  const { db } = c;
  const [plans, subs, setting] = await Promise.all([
    db.from("plans").select("id, name, period, amount_paise, active, razorpay_plan_id, razorpay_offer_id, offer_name, offer_amount_paise, offer_ends_at, offer_limit").order("created_at"),
    db.from("subscriptions").select("plan_id, status, plan_amount_paise, offer_applied").eq("status", "active"),
    db.from("app_settings").select("value").eq("key", "trial_days").maybeSingle(),
  ]);
  if (plans.error || subs.error) return null;
  const rows = (plans.data ?? []) as AdminPlan[];
  const days = Number(setting.data?.value);
  return { plans: rows, revenue: revenueByPlan(rows, subs.data ?? []), trialDays: Number.isInteger(days) ? days : 7, mode: razorpayMode(process.env.RAZORPAY_KEY_ID) };
}

export async function changePrice(planId: string, rupees: string): Promise<Result> {
  const c = await context();
  if (!c) return NOT_ADMIN;
  const { ctx, db, auth } = c;
  if (!auth) return fail("Razorpay is not configured on this server.");
  const { data: plan } = await db.from("plans").select("*").eq("id", planId).maybeSingle();
  if (!plan) return fail("No such plan.");
  const check = validatePriceChange(plan, rupees);
  if (!check.ok) return fail(check.error);

  const swapped = await recreateAtRazorpay(c, plan, check.newPaise, { column: "amount_paise", value: check.oldPaise }, "plan_price_failed", "plan_price_change", { old_paise: check.oldPaise, new_paise: check.newPaise });
  if (!swapped.ok) return swapped;
  return { ok: true, message: "Price changed. New sign-ups pay it; existing subscribers keep their price. The early-bird offer was cleared: add it again for the new plan." + swapped.note };
}

/**
 * Re-creates the plan at its current price under whichever Razorpay account the
 * server's keys belong to, e.g. after switching test keys for live ones. The row
 * is guarded by its old razorpay_plan_id, so a double click saves once.
 */
export async function relinkPlan(planId: string): Promise<Result> {
  const c = await context();
  if (!c) return NOT_ADMIN;
  if (!c.auth) return fail("Razorpay is not configured on this server.");
  const { data: plan } = await c.db.from("plans").select("*").eq("id", planId).maybeSingle();
  if (!plan) return fail("No such plan.");
  const swapped = await recreateAtRazorpay(c, plan, plan.amount_paise, { column: "razorpay_plan_id", value: plan.razorpay_plan_id ?? null }, "plan_relink_failed", "plan_relinked", { paise: plan.amount_paise });
  if (!swapped.ok) return swapped;
  return { ok: true, message: `Plan re-created in Razorpay (${razorpayMode(process.env.RAZORPAY_KEY_ID)} account) at the same price. The early-bird offer was cleared: add it again from that account.` + swapped.note };
}

/**
 * Razorpay plans cannot be edited: make a new one and point the row at it
 * (shared by a price change and a relink). The offer was attached to the old
 * plan and ends with it. Compare-and-set via swapPlan.
 */
async function recreateAtRazorpay(
  c: NonNullable<Awaited<ReturnType<typeof context>>>,
  plan: AdminPlan,
  newPaise: number,
  guard: { column: string; value: string | number | null },
  failedAction: string,
  doneAction: string,
  detail: Record<string, unknown>,
): Promise<{ ok: true; note: string } | { ok: false; error: string }> {
  const { ctx, db, auth } = c;
  const response = await fetch(`${RAZORPAY}/plans`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: auth as string },
    body: JSON.stringify(razorpayPlanBody(plan, newPaise)),
  }).catch(() => null);
  const created = response?.ok ? await response.json().catch(() => null) : null;
  if (!created?.id) return fail("Razorpay did not create the plan. Nothing changed.") as { ok: false; error: string };

  const swapped = await swapPlan(db, plan.id, guard, { amount_paise: newPaise, razorpay_plan_id: created.id });
  if (swapped.result === "stale") {
    const note = await logAdminAction(ctx, failedAction, {}, { plan: plan.id, reason: "changed meanwhile", unused_razorpay_plan_id: created.id, ...detail });
    return { ok: false, error: `The plan changed meanwhile, so nothing was saved. Reload the page. An unused Razorpay plan ${created.id} was created; ignore it.${note}` };
  }
  if (swapped.result === "error") {
    await logAdminAction(ctx, failedAction, {}, { plan: plan.id, new_razorpay_plan_id: created.id, error: swapped.message, ...detail });
    return { ok: false, error: `The Razorpay plan ${created.id} was created but our row did not update. Nothing is on sale at the new plan; tell the developer.` };
  }
  const note = await logAdminAction(ctx, doneAction, {}, {
    plan: plan.id, ...detail,
    old_razorpay_plan_id: plan.razorpay_plan_id, new_razorpay_plan_id: created.id,
    cleared_offer: plan.razorpay_offer_id,
  });
  return { ok: true, note };
}

export type OfferInput = { name: string; rupees: string; offerId: string; endsAt: string; limit: string };

export async function saveOffer(planId: string, input: OfferInput): Promise<Result> {
  const c = await context();
  if (!c) return NOT_ADMIN;
  const { ctx, db } = c;
  const { data: plan } = await db.from("plans").select("*").eq("id", planId).maybeSingle();
  if (!plan) return fail("No such plan.");
  const check = validateOffer(plan, input);
  if (!check.ok) return fail(check.error);
  const { error } = await db.from("plans").update(check.offer).eq("id", planId);
  if (error) return fail("Could not save the offer.");
  const note = await logAdminAction(ctx, check.offer.razorpay_offer_id ? "plan_offer_set" : "plan_offer_cleared", {}, {
    plan: planId,
    before: { name: plan.offer_name, paise: plan.offer_amount_paise, ends_at: plan.offer_ends_at, limit: plan.offer_limit, id: plan.razorpay_offer_id },
    after: check.offer,
  });
  return { ok: true, message: check.offer.razorpay_offer_id ? "Offer saved. It is not checked at Razorpay (there is no lookup): make sure the id is right and its amount matches the price you typed." + note : "Offer removed." + note };
}

export async function setPlanOpen(planId: string, open: boolean): Promise<Result> {
  const c = await context();
  if (!c) return NOT_ADMIN;
  const { ctx, db } = c;
  const { data, error } = await db.from("plans").update({ active: open }).eq("id", planId).select("id");
  if (error || !data?.length) return fail("Could not update the plan.");
  const note = await logAdminAction(ctx, open ? "plan_open" : "plan_close", {}, { plan: planId });
  return { ok: true, message: (open ? "Plan is on sale." : "Plan closed for sale. Existing subscribers are not affected.") + note };
}

export async function setTrialDays(input: string): Promise<Result> {
  const c = await context();
  if (!c) return NOT_ADMIN;
  const { ctx, db } = c;
  const check = validateTrialDays(input);
  if (!check.ok) return fail(check.error);
  const { data: before } = await db.from("app_settings").select("value").eq("key", "trial_days").maybeSingle();
  const { error } = await db.from("app_settings").upsert({ key: "trial_days", value: check.days, updated_at: new Date().toISOString() });
  if (error) return fail("Could not save the trial length. Has storage/admin_plans_schema.sql been applied?");
  const note = await logAdminAction(ctx, "setting_update", {}, { setting: "trial_days", before: before?.value ?? null, after: check.days });
  return { ok: true, message: `New sign-ups get ${check.days} days. Trials already running are not changed.` + note };
}
