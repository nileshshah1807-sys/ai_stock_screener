import "server-only";

import {
  offerLookupVerdict,
  razorpayPlanBody,
  revenueByPlan,
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
  return { plans: rows, revenue: revenueByPlan(rows, subs.data ?? []), trialDays: Number.isInteger(days) ? days : 7 };
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

  // Razorpay plans cannot be edited: make a new one. Subscribers keep theirs.
  const response = await fetch(`${RAZORPAY}/plans`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: auth },
    body: JSON.stringify(razorpayPlanBody(plan, check.newPaise)),
  }).catch(() => null);
  const created = response?.ok ? await response.json().catch(() => null) : null;
  if (!created?.id) return fail("Razorpay did not create the plan. Nothing changed.");

  // The offer was priced against the old plan and attached to it: it ends with it.
  // Compare-and-set on the old price: a double click or a second admin cannot overwrite a change made meanwhile.
  const { data: changed, error } = await db
    .from("plans")
    .update({
      amount_paise: check.newPaise,
      razorpay_plan_id: created.id,
      offer_name: null, offer_amount_paise: null, offer_ends_at: null, offer_limit: null, razorpay_offer_id: null,
    })
    .eq("id", planId)
    .eq("amount_paise", check.oldPaise)
    .select("id");
  if (!error && !changed?.length) {
    const note = await logAdminAction(ctx, "plan_price_failed", {}, { plan: planId, reason: "price changed meanwhile", unused_razorpay_plan_id: created.id, new_paise: check.newPaise });
    return fail(`The price changed meanwhile, so nothing was saved. Reload the page. An unused Razorpay plan ${created.id} was created; ignore it.${note}`);
  }
  if (error) {
    await logAdminAction(ctx, "plan_price_failed", {}, { plan: planId, new_razorpay_plan_id: created.id, new_paise: check.newPaise, error: error.message });
    return fail(`The Razorpay plan ${created.id} was created but our row did not update. Nothing is on sale at the new price; tell the developer.`);
  }
  const note = await logAdminAction(ctx, "plan_price_change", {}, {
    plan: planId,
    old_paise: check.oldPaise, new_paise: check.newPaise,
    old_razorpay_plan_id: plan.razorpay_plan_id, new_razorpay_plan_id: created.id,
    cleared_offer: plan.razorpay_offer_id,
  });
  return { ok: true, message: "Price changed. New sign-ups pay it; existing subscribers keep their price. The early-bird offer was cleared: add it again for the new plan." + note };
}

export type OfferInput = { name: string; rupees: string; offerId: string; endsAt: string; limit: string };

export async function saveOffer(planId: string, input: OfferInput): Promise<Result> {
  const c = await context();
  if (!c) return NOT_ADMIN;
  const { ctx, db, auth } = c;
  const { data: plan } = await db.from("plans").select("*").eq("id", planId).maybeSingle();
  if (!plan) return fail("No such plan.");
  const check = validateOffer(plan, input);
  if (!check.ok) return fail(check.error);

  let verified: boolean | null = null;
  if (check.offer.razorpay_offer_id) {
    if (!auth) return fail("Billing is not configured on this server.");
    const found = await fetch(`${RAZORPAY}/offers/${check.offer.razorpay_offer_id}`, { headers: { Authorization: auth } }).catch(() => null);
    const verdict = offerLookupVerdict(found?.status ?? 0);
    if (!verdict.ok) return fail(verdict.error);
    verified = verdict.verified;
  }
  const { error } = await db.from("plans").update(check.offer).eq("id", planId);
  if (error) return fail("Could not save the offer.");
  const note = await logAdminAction(ctx, check.offer.razorpay_offer_id ? "plan_offer_set" : "plan_offer_cleared", {}, {
    plan: planId,
    before: { name: plan.offer_name, paise: plan.offer_amount_paise, ends_at: plan.offer_ends_at, limit: plan.offer_limit, id: plan.razorpay_offer_id },
    after: check.offer,
  });
  return { ok: true, message: check.offer.razorpay_offer_id ? (verified ? "Offer saved." : "Offer saved. Razorpay could not confirm the id; check it in the dashboard.") + note : "Offer removed." + note };
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
