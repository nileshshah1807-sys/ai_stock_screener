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
  // A legacy subscription scheduled to start at the trial end would charge late: start afresh.
  const waits = Number.isFinite(remote.start_at) && remote.start_at * 1000 > Date.now();
  return remote.status === "created" && remote.plan_id === razorpayPlanId && !waits ? "reuse" : "create";
}

/**
 * What restricts Razorpay Checkout to UPI. The early-bird offer is attached to
 * UPI only, so a card payer would be charged the full price: while the offer is
 * applied, checkout offers UPI alone. `method` switches the plain methods off;
 * a subscription still lists eMandate unless `config` shows only a UPI block
 * (seen in test mode). Without the offer, {} leaves every method on.
 */
export function checkoutRestriction(offerApplied) {
  if (!offerApplied) return {};
  return {
    method: { upi: true, card: false, netbanking: false, wallet: false, emi: false, paylater: false, emandate: false },
    config: {
      display: {
        blocks: { upi: { name: "Pay with UPI", instruments: [{ method: "upi" }] } },
        sequence: ["block.upi"],
        preferences: { show_default_blocks: false },
      },
    },
  };
}

/** Subscriptions are charged until cancelled; Razorpay needs a finite count. */
const TOTAL_COUNT = { monthly: 120, yearly: 10 };

/**
 * The body for Razorpay's create-subscription call. No start_at: buying ends
 * the trial, so the first charge is made now, in or out of the trial.
 */
export function newSubscriptionBody({ plan, userId, offerId }) {
  /** @type {{plan_id: string, total_count: number, customer_notify: number, notes: {user_id: string, plan_id: string}, offer_id?: string}} */
  const body = {
    plan_id: plan.razorpay_plan_id,
    total_count: TOTAL_COUNT[plan.period],
    customer_notify: 1,
    notes: { user_id: userId, plan_id: plan.id },
  };
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

export const TRIAL_UNAVAILABLE =
  "A free trial was already used from this device, network or email address, so this account has none. Subscribe to get access.";

/**
 * Why a lapsed person is on the pricing page, from their subscription row.
 * No row, or a trial that ran out, is the trial ending; a refused trial is its own reason.
 * @param {string|undefined} status
 * @param {string|null|undefined} [trialDeniedAt]
 */
export function lapseReason(status, trialDeniedAt) {
  if (trialDeniedAt) return "trial_unavailable";
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

/**
 * What the trial banner adds once a plan is set up: "Cupel Monthly starts 12 Nov,
 * first charge ₹129" (a yearly plan: its offer price if offer_applied, its price if not, none if unrecorded). The price is the plan's own. Null
 * when nothing is set up, or the plan or the date is unknown.
 */
export function trialStartLine(subscription, plan) {
  if (!isSetUp(subscription) || subscription.status !== "trialing" || !plan) return null;
  if (!subscription.trial_ends_at) return null;
  const when = new Date(subscription.trial_ends_at);
  if (Number.isNaN(when.getTime())) return null;
  const day = when.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
  const paise = firstChargePaise(subscription, plan);
  return paise == null ? `${plan.name} starts ${day}` : `${plan.name} starts ${day}, first charge ${priceLabel(paise)}`;
}

/**
 * The first charge. A yearly plan may have been taken at its introductory price;
 * the row says which (offer_applied null: not recorded, so no amount).
 */
export function firstChargePaise(subscription, plan) {
  const price = subscription.plan_amount_paise ?? plan.amount_paise;
  if (plan.period !== "yearly") return price;
  if (subscription.offer_applied === true) return plan.offer_amount_paise ?? null;
  return subscription.offer_applied === false ? price : null;
}

// --- The pricing and account pages' wording ---

/** Both launch plans share one name, so the page names a plan by its period. */
export function planTitle(plan) {
  return plan?.period === "yearly" ? "Yearly plan" : plan?.period === "monthly" ? "Monthly plan" : "Your plan";
}

/** The plan a person has set up (paid, or authorised and waiting out the trial), else null. */
export function currentPlanId(subscription) {
  return isSetUp(subscription) ? (subscription.plan_id ?? null) : null;
}

/**
 * The account page's plan card as words. `fmtDate` and `fmtMoney` are the page's
 * formatters, so this stays plain and testable. `nextCharge` is null when no
 * charge is coming. The first charge follows the row's offer_applied, never today's offer.
 * @returns {{title: string, status: string, detail: string, nextCharge: {date: string|null, paise: number}|null}}
 */
export function planSummary({ kind, subscription, plan }, fmtDate, fmtMoney = priceLabel) {
  if (kind === "admin") return { title: "Administrator", status: "Full access", detail: "Your account has full access, with no end date.", nextCharge: null };
  if (kind === "allowlist") return { title: "Invited account", status: "Full access", detail: "Your account was invited and has full access, with no end date.", nextCharge: null };

  const title = planTitle(plan);
  const lapsed = kind === "lapsed";
  switch (subscription?.status) {
    case "active": {
      const paise = subscription.plan_amount_paise ?? plan?.amount_paise;
      const date = subscription.current_period_end;
      return {
        title,
        status: "Active",
        detail: `Renews on ${fmtDate(date)}${paise != null ? ` for ${fmtMoney(paise)}` : ""}.`,
        nextCharge: paise != null ? { date, paise } : null,
      };
    }
    case "trialing": {
      const date = subscription.trial_ends_at;
      if (!subscription.plan_id) {
        return lapsed
          ? { title: "No plan", status: "Free trial ended", detail: "Subscribe to get access back.", nextCharge: null }
          : { title: "Free trial", status: "Free trial", detail: `Your trial ends on ${fmtDate(date)}. Pick a plan before then to keep access. Nothing is charged until it ends.`, nextCharge: null };
      }
      const line = plan ? trialStartLine(subscription, plan) : null;
      const paise = plan ? firstChargePaise(subscription, plan) : null;
      return {
        title,
        status: "Free trial",
        detail: line ? `Free trial, ${line}.` : "Free trial. Your plan starts when the trial ends.",
        nextCharge: paise != null ? { date, paise } : null,
      };
    }
    case "past_due":
      return { title, status: "Payment failed", detail: "Your last payment did not go through, so access has paused.", nextCharge: null };
    case "cancelled":
      return lapsed
        ? { title, status: "Cancelled", detail: "Your plan has ended. Subscribe to get access back.", nextCharge: null }
        : { title, status: "Cancelled", detail: `Access until ${fmtDate(subscription.current_period_end ?? subscription.trial_ends_at)}. You will not be charged again.`, nextCharge: null };
    default:
      if (subscription?.trial_denied_at) return { title: "No plan", status: "No free trial", detail: TRIAL_UNAVAILABLE, nextCharge: null };
      return { title: "No plan", status: lapsed ? "Free trial ended" : "No plan", detail: lapsed ? "Subscribe to get access back." : "Pick a plan to get started.", nextCharge: null };
  }
}
