/**
 * The pure rules of self-serve billing: who has access, and what a Razorpay
 * subscription event changes.
 *
 * Plain .mjs so `node --test` covers it without a build step. The access rule
 * is kept equal to dashboard_has_access() in storage/billing_schema.sql by
 * its test; the price is never here (it is plans.amount_paise).
 */

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
 * (not a subscription event, or a plain `created`); `authenticated` carries no status.
 * `eventId` is Razorpay's X-Razorpay-Event-Id header.
 */
export function subscriptionChange(event, eventId) {
  const entity = event?.payload?.subscription?.entity;
  if (!String(event?.event ?? "").startsWith("subscription.") || !entity?.id) return null;
  // A mandate authorised during the trial changes no status, only the plan.
  const status = entity.status === "authenticated" ? null : STATUS[entity.status];
  if (entity.status !== "authenticated" && !status) return null;
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
 * What checkout does for a user, given their subscriptions row and, when the row
 * holds a Razorpay subscription, that subscription as Razorpay reports it.
 * Two authorised subscriptions would both charge, so: refuse when one is set up
 * (the mandate is authorised, or it is paid), reuse one still awaiting
 * authorisation, create only otherwise. Returns "refuse" | "reuse" | "create".
 */
export function checkoutAction(row, remote, razorpayPlanId) {
  if (!row) return "create";
  if (row.status === "active" || (row.plan_id && ["trialing", "past_due"].includes(row.status))) return "refuse";
  if (!remote) return "create";
  if (["authenticated", "active"].includes(remote.status)) return "refuse";
  return remote.status === "created" && remote.plan_id === razorpayPlanId ? "reuse" : "create";
}

/** Subscriptions are charged until cancelled; Razorpay needs a finite count. */
const TOTAL_COUNT = { monthly: 120, yearly: 10 };
/** A first charge less than this far ahead is simply charged now. */
const MIN_TRIAL_LEAD_SECONDS = 60 * 60;

/**
 * The body for Razorpay's create-subscription call. With trial time left the
 * first charge waits for it (the mandate is authorised now); else it is now.
 */
export function newSubscriptionBody({ plan, userId, trialEndsAt, offerId }, nowSeconds) {
  /** @type {{plan_id: string, total_count: number, customer_notify: number, notes: {user_id: string, plan_id: string}, start_at?: number, offer_id?: string}} */
  const body = {
    plan_id: plan.razorpay_plan_id,
    total_count: TOTAL_COUNT[plan.period],
    customer_notify: 1,
    notes: { user_id: userId, plan_id: plan.id },
  };
  const trialEnd = trialEndsAt ? Math.floor(Date.parse(trialEndsAt) / 1000) : 0;
  if (trialEnd - nowSeconds > MIN_TRIAL_LEAD_SECONDS) body.start_at = trialEnd;
  if (offerId) body.offer_id = offerId;
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

// --- Pages: what the plan allows, in words (used by lib/auth.ts and the billing pages) ---

const DAY_SECONDS = 24 * 60 * 60;

/**
 * What a token's claims allow, in the words the pages use. The yes/no is main's
 * hasAccess() above (so the same integer access_until rule); this adds why not,
 * and how long is left.
 * @returns {{kind: "legacy"|"admin"|"allowlist"|"trial"|"paid"|"lapsed", plan: string|null, until: number|null, daysLeft: number|null}}
 */
export function accessFromClaims(claims, nowSeconds = Date.now() / 1000) {
  const plan = typeof claims?.plan === "string" ? claims.plan : null;
  const until = Number.isInteger(claims?.access_until) ? claims.access_until : null;
  if (plan === null) return { kind: "legacy", plan, until, daysLeft: null };
  if (PERMANENT_PLANS.includes(plan)) return { kind: plan, plan, until: null, daysLeft: null };
  if (!hasAccess(claims, nowSeconds)) return { kind: "lapsed", plan, until, daysLeft: 0 };
  // Whole days, rounded up: 2 hours left reads "1 day left", never "0 days".
  const daysLeft = Math.ceil((until - nowSeconds) / DAY_SECONDS);
  return { kind: plan === "trial" ? "trial" : "paid", plan, until, daysLeft };
}

/** Whether an accessFromClaims() result lets the person in. */
export function isEntitled(access) {
  return access.kind !== "lapsed";
}

/** "1 day left", "5 days left". */
export function daysLeftLabel(days) {
  return `${days} ${days === 1 ? "day" : "days"} left`;
}

/**
 * A plan's price as stored: paise in, rupees out, shown exactly as held.
 * Whole rupees print without decimals; anything else keeps two.
 */
export function priceLabel(amountPaise) {
  const rupees = Number(amountPaise) / 100;
  if (!Number.isFinite(rupees)) return "";
  const text = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: Number.isInteger(rupees) ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(rupees);
  return `₹${text}`;
}

export const PERIOD_LABEL = { monthly: "month", yearly: "year" };

/**
 * Why a lapsed person is on the pricing page, from their subscription row.
 * No row, or a trial that ran out, is the trial ending.
 */
export function lapseReason(status) {
  if (status === "cancelled") return "cancelled";
  if (status === "past_due") return "past_due";
  return "trial_ended";
}

/** The subscription is set up: paid now, or authorised and waiting for the trial to end. */
export function isSetUp(row) {
  return row?.status === "active" || (row?.status === "trialing" && Boolean(row?.plan_id));
}

/** A plan's monthly equivalent in paise: a yearly price over twelve. */
export function perMonthPaise(plan) {
  const amount = Number(plan?.amount_paise);
  if (!Number.isFinite(amount)) return null;
  return plan.period === "yearly" ? amount / 12 : amount;
}

/**
 * How much less per month the yearly plan costs than the monthly one, as a
 * whole percent; null unless there are both and the yearly really is cheaper.
 */
export function savingPercent(yearly, monthly) {
  const year = perMonthPaise(yearly);
  const month = perMonthPaise(monthly);
  if (year === null || month === null || year >= month) return null;
  return Math.round((1 - year / month) * 100);
}

/** The monthly equivalent for display: "about" is the caller's word, rounded to whole rupees. */
export function perMonthLabel(plan) {
  const paise = perMonthPaise(plan);
  return paise === null ? "" : priceLabel(Math.round(paise / 100) * 100);
}
