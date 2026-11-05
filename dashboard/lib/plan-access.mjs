/**
 * What a signed-in person's plan lets them do, read from the access token.
 *
 * The token carries two claims, set by the database's access-token hook:
 * `plan` -- 'admin', 'allowlist' (invited before sign-up opened, no expiry),
 * 'trial', a plans.id (paid) or 'none' -- and `access_until`, epoch seconds,
 * absent for admin and allowlist. Access is the plan being admin or allowlist,
 * or any other plan but 'none' whose access_until is still ahead. Claims change
 * only when the token is refreshed, so a payment is followed by a refresh.
 *
 * A token with no `plan` claim at all is one issued before the hook existed;
 * the caller falls back to the invite list for it.
 *
 * Plain .mjs so `node --test` covers it without a build step.
 */

const DAY_SECONDS = 24 * 60 * 60;

/** @returns {{kind: "legacy"|"admin"|"allowlist"|"trial"|"paid"|"lapsed", plan: string|null, until: number|null, daysLeft: number|null}} */
export function accessFromClaims(claims, nowSeconds = Date.now() / 1000) {
  const plan = typeof claims?.plan === "string" ? claims.plan : null;
  const until = claims?.access_until != null && Number.isFinite(Number(claims.access_until)) ? Number(claims.access_until) : null;
  if (plan === null) return { kind: "legacy", plan, until, daysLeft: null };
  if (plan === "admin" || plan === "allowlist") return { kind: plan, plan, until: null, daysLeft: null };
  if (plan === "none" || until === null || until <= nowSeconds) return { kind: "lapsed", plan, until, daysLeft: 0 };
  // Whole days, rounded up: 2 hours left reads "1 day left", never "0 days".
  const daysLeft = Math.ceil((until - nowSeconds) / DAY_SECONDS);
  return { kind: plan === "trial" ? "trial" : "paid", plan, until, daysLeft };
}

export function hasAccess(access) {
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
