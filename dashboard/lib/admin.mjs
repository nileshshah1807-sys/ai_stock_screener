/**
 * The pure rules of the /admin page: who may use it, how a user row is put
 * together, and what each action changes. No I/O, so `node --test` covers it;
 * lib/admin.ts runs the plans it returns with the service role.
 */
import { cleanDisplayName } from "./display-name.mjs";

const DAY_MS = 86_400_000;
export const MAX_TRIAL_DAYS = 365;
/** Statuses a subscriptions row can hold, in the order the filter lists them. */
export const STATUSES = ["trialing", "active", "past_due", "cancelled", "expired"];
export const FILTERS = ["all", ...STATUSES, "denied", "complimentary", "admin", "none"];

/**
 * The one permission check. `viewer` is what getViewer() returns, built from a
 * verified token (getClaims) on this request; nothing the client sent is read.
 */
export function canAdminister(viewer) {
  return Boolean(viewer && viewer.id && viewer.role === "admin");
}

export function isEmail(value) {
  const email = String(value ?? "").trim();
  return email.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email);
}

export const cleanEmail = (value) => String(value ?? "").trim().toLowerCase();

/** A whole number of days, 1..MAX_TRIAL_DAYS, or null. */
export function parseDays(raw) {
  const text = String(raw ?? "").trim();
  if (!/^\d+$/.test(text)) return null;
  const days = Number(text);
  return days >= 1 && days <= MAX_TRIAL_DAYS ? days : null;
}

const iso = (ms) => new Date(ms).toISOString();

/**
 * The plan claim the token hook would write for this user
 * (custom_access_token_hook in storage/billing_schema.sql).
 * @param {{role?: string|null}|null} member their dashboard_allowlist row
 */
export function planClaim(member, sub, now = Date.now()) {
  if (member?.role === "admin") return "admin";
  if (member) return "allowlist";
  if (!sub || sub.status === "expired") return "none";
  const ends = [sub.current_period_end, sub.trial_ends_at].map((v) => (v ? Date.parse(v) : NaN)).filter(Number.isFinite);
  if (!ends.length || Math.max(...ends) <= now) return "none";
  return sub.status === "trialing" ? "trial" : (sub.plan_id ?? "none");
}

/** When the next charge falls: the period end of a paid subscription, or the trial end of one that has a mandate. */
export function nextCharge(sub) {
  if (!sub) return null;
  if (sub.status === "active" || sub.status === "past_due") return sub.current_period_end ?? null;
  if (sub.status === "trialing" && sub.razorpay_subscription_id) return sub.trial_ends_at ?? null;
  return null;
}

/** "granted", "denied" (with the reason), or null when the guard never ran for them. */
export function guardResult(signal, sub) {
  if (!signal && !sub?.trial_denied_at) return null;
  const denied = signal ? !signal.granted : true;
  return { result: denied ? "denied" : "granted", reason: signal?.reason ?? null };
}

/** One table row from an auth user and the rows that belong to them. */
export function buildRow(user, sub, signal, member, now = Date.now()) {
  const email = cleanEmail(user.email);
  const name = user.user_metadata?.full_name;
  return {
    id: user.id,
    email,
    name: typeof name === "string" ? name : "",
    created_at: user.created_at ?? null,
    last_sign_in_at: user.last_sign_in_at ?? null,
    plan_claim: planClaim(member, sub, now),
    role: member?.role ?? null,
    status: sub?.status ?? null,
    trial_ends_at: sub?.trial_ends_at ?? null,
    next_charge: nextCharge(sub),
    razorpay_subscription_id: sub?.razorpay_subscription_id ?? null,
    guard: guardResult(signal, sub),
    complimentary: member?.role === "viewer",
  };
}

/** Search by email or name; filter by status, trial denial, complimentary access, admin or no plan. */
export function filterRows(rows, { q = "", status = "all" } = {}) {
  const needle = String(q).trim().toLowerCase();
  return rows.filter((row) => {
    if (needle && !row.email.includes(needle) && !row.name.toLowerCase().includes(needle)) return false;
    switch (status) {
      case "all":
        return true;
      case "denied":
        return row.guard?.result === "denied";
      case "complimentary":
        return row.complimentary;
      case "admin":
        return row.role === "admin";
      case "none":
        return row.plan_claim === "none";
      default:
        return row.status === status;
    }
  });
}

export const asFilter = (value) => (FILTERS.includes(value) ? value : "all");

/** Razorpay dashboard record for a subscription; test keys have their own prefix. */
export function razorpayUrl(subscriptionId, keyId = "") {
  if (!subscriptionId || !/^sub_\w+$/.test(subscriptionId)) return null;
  return `https://dashboard.razorpay.com/${String(keyId).startsWith("rzp_test") ? "test/" : ""}app/subscriptions/${subscriptionId}`;
}

/**
 * Extend adds days to the later of now and the current trial end; restart sets
 * the end to now + days and lifts a denial. A paid (active) subscription is not
 * touched: its trial is over, and a trial row would hide the paid status.
 * @returns {{ok: boolean, message?: string, patch?: {status: string, trial_ends_at: string, updated_at: string, trial_denied_at?: null}}}
 */
export function trialPlan(sub, mode, days, now = Date.now()) {
  if (!["extend", "restart"].includes(mode)) return { ok: false, message: "Choose extend or restart." };
  if (!Number.isInteger(days) || days < 1 || days > MAX_TRIAL_DAYS) return { ok: false, message: `Use 1 to ${MAX_TRIAL_DAYS} days.` };
  if (!sub) return { ok: false, message: "This user has no subscription row." };
  if (sub.status === "active") return { ok: false, message: "This user pays already; there is no trial to change." };
  const current = sub.trial_ends_at ? Date.parse(sub.trial_ends_at) : NaN;
  const from = mode === "extend" && Number.isFinite(current) ? Math.max(current, now) : now;
  const patch = { status: "trialing", trial_ends_at: iso(from + days * DAY_MS), updated_at: iso(now) };
  if (mode === "restart") patch.trial_denied_at = null;
  return { ok: true, patch };
}

/**
 * Complimentary access is a viewer row in dashboard_allowlist. An admin's row is
 * never written or removed here: the role stays a SQL change.
 */
export function complimentaryPlan(member, grant) {
  if (member?.role === "admin") return { ok: false, message: "Admin access is changed in SQL, not here." };
  if (grant) return member ? { ok: false, message: "Already has complimentary access." } : { ok: true, op: "insert" };
  return member ? { ok: true, op: "delete" } : { ok: false, message: "No complimentary access to remove." };
}

/** The two statements at the bottom of storage/trial_guard_schema.sql, as patches. */
export function undoDenialPlan(sub, signal, now = Date.now()) {
  if (!sub?.trial_denied_at && !(signal && !signal.granted)) return { ok: false, message: "No trial denial to undo." };
  return {
    ok: true,
    subscription: { status: "trialing", trial_ends_at: iso(now + 7 * DAY_MS), trial_denied_at: null, updated_at: iso(now) },
    signal: { granted: false, reason: "overridden" },
  };
}

export function namePlan(raw) {
  return cleanDisplayName(raw);
}

/**
 * Deleting: the typed address must match, an admin or yourself cannot be deleted
 * here, and a live Razorpay subscription is cancelled first (at once: there is
 * no one left to serve the rest of the period).
 */
export function deletePlan({ actorId, target, sub, typedEmail }) {
  if (!target) return { ok: false, message: "User not found." };
  if (target.id === actorId) return { ok: false, message: "You cannot delete yourself." };
  if (target.role === "admin") return { ok: false, message: "Admins are removed in SQL, not here." };
  if (cleanEmail(typedEmail) !== cleanEmail(target.email)) return { ok: false, message: "The address typed does not match." };
  const live = Boolean(sub?.razorpay_subscription_id) && !["cancelled", "expired"].includes(sub.status);
  return { ok: true, cancelFirst: live ? sub.razorpay_subscription_id : null };
}

/** Other admin pages (plans, settings) log their own actions: a lower-case word with underscores. */
export const isActionName = (action) => /^[a-z][a-z_]{2,39}$/.test(String(action));

/** The line written to admin_actions. */
export function logEntry(actor, action, target, detail = {}, now = Date.now()) {
  if (!isActionName(action)) throw new Error(`unknown admin action: ${action}`);
  return {
    admin_id: actor.id,
    admin_email: actor.email,
    action,
    target_id: target.id ?? null,
    target_email: target.email ?? null,
    detail,
    created_at: iso(now),
  };
}
